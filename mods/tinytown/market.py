"""Player-created whiteboard art listings and print sales."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import uuid

from mods.tinytown.art import ART_PIECES, art_payload
from mods.tinytown.catalog import (
    ART_PRICE_MAX,
    ART_PRICE_MIN,
    MAX_ART_LISTINGS,
)
from server.content.surface_props import MAX_WHITEBOARD_PROPS, WHITEBOARD_PROP_ID
from server.security import utc_now
from server.services.room_layout import LayoutUpdate


MAX_LISTING_TITLE = 80
MAX_LISTING_DESCRIPTION = 240
MAX_MARKET_LISTINGS = 120
WHITEBOARD_SLOTS = ((18.0, 9.0), (39.0, 9.0), (61.0, 9.0), (82.0, 9.0))


@dataclass(frozen=True, slots=True)
class ArtListing:
    listing_id: str
    seller_id: str
    source_room_id: str
    source_instance_id: str
    title: str
    description: str
    price: int
    surface: dict[str, object]
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class MarketPurchase:
    message: str
    listing: dict[str, object]
    layout_event: dict[str, object]
    surface_event: dict[str, object]
    bops_spent: int


class TinyTownArtMarket:
    """Owns community art listings, sales, and settlement."""

    def __init__(self, housing: object) -> None:
        self.housing = housing
        self.runtime = housing.runtime
        self.world = housing.runtime.world
        self.hub = housing.runtime.hub
        self.profiles = housing.runtime.profiles
        self.layout = housing.runtime.layout
        self.surfaces = housing.runtime.surfaces
        self.world_state = housing.runtime.world_state

    def _listing_from_row(self, row: object) -> ArtListing:
        try:
            surface = json.loads(row["surface_json"])
        except (TypeError, ValueError):
            surface = {}
        return ArtListing(
            listing_id=str(row["listing_id"]),
            seller_id=str(row["seller_account_id"]),
            source_room_id=str(row["source_room_id"]),
            source_instance_id=str(row["source_instance_id"]),
            title=str(row["title"]),
            description=str(row["description"]),
            price=int(row["price"]),
            surface=surface if isinstance(surface, dict) else {},
            status=str(row["status"]),
            created_at=str(row["created_at"]),
        )

    def _listing(self, listing_id: str) -> ArtListing | None:
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.tinytown_art_listings WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
        return self._listing_from_row(row) if row is not None else None

    def _rows(self, *, status: str = "active", seller_id: str | None = None) -> list[ArtListing]:
        query = "SELECT * FROM world.tinytown_art_listings WHERE status = ?"
        parameters: list[object] = [status]
        if seller_id:
            query += " AND seller_account_id = ?"
            parameters.append(seller_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(MAX_MARKET_LISTINGS)
        with self.hub.locked() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._listing_from_row(row) for row in rows]

    def _owned_listing_ids(self, buyer_id: str) -> set[str]:
        with self.hub.locked() as connection:
            rows = connection.execute(
                "SELECT listing_id FROM world.tinytown_art_sales WHERE buyer_account_id = ?",
                (buyer_id,),
            ).fetchall()
        return {str(row["listing_id"]) for row in rows}

    def _seller_name(self, seller_id: str) -> str:
        account = self.profiles.get_account_by_id(seller_id)
        return account.username_display if account is not None else "Former resident"

    def listing_payload(self, listing: ArtListing, viewer_id: str, owned: bool = False) -> dict[str, object]:
        return {
            "id": listing.listing_id,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "seller_id": listing.seller_id,
            "seller_username": self._seller_name(listing.seller_id),
            "is_seller": listing.seller_id == viewer_id,
            "owned": owned,
            "surface": dict(listing.surface),
            "source_room_id": listing.source_room_id,
            "created_at": listing.created_at,
        }

    def active_listings(self, viewer_id: str) -> list[dict[str, object]]:
        owned = self._owned_listing_ids(viewer_id)
        return [
            self.listing_payload(listing, viewer_id, listing.listing_id in owned)
            for listing in self._rows()
        ]

    def my_listings(self, account: object) -> list[dict[str, object]]:
        return [
            self.listing_payload(listing, account.id)
            for listing in self._rows(status="active", seller_id=account.id)
        ]

    def sellables(self, account: object) -> list[dict[str, object]]:
        """List editable whiteboards across all owned homes."""

        active_sources = {
            (listing.source_room_id, listing.source_instance_id): listing
            for listing in self._rows(status="active", seller_id=account.id)
        }
        results: list[dict[str, object]] = []
        for house in self.housing.records_for_owner(account.id):
            try:
                template = self.housing.template_for(house)
            except ValueError:
                continue
            for room_key, room_id in house.room_ids.items():
                if room_id not in self.world.rooms:
                    continue
                try:
                    layout = self.layout.view(account, room_id)
                except (KeyError, ValueError):
                    continue
                room_label = next(
                    (room.label for room in template.rooms if room.key == room_key),
                    self.world.rooms[room_id].label,
                )
                for prop in layout.get("props", []):
                    if str(prop.get("prop_id")) != WHITEBOARD_PROP_ID:
                        continue
                    instance_id = str(prop.get("id"))
                    surface = self.surfaces.get(room_id, instance_id, "whiteboard")
                    if surface.locked or not surface.content:
                        continue
                    if not surface.content.get("strokes") and not surface.content.get("texts"):
                        continue
                    active = active_sources.get((room_id, instance_id))
                    results.append(
                        {
                            "room_id": room_id,
                            "instance_id": instance_id,
                            "room_label": room_label,
                            "house_label": template.label,
                            "surface": surface.serialize(),
                            "listing_id": active.listing_id if active else "",
                            "listed": active is not None,
                        }
                    )
        return results

    def sell(
        self,
        account: object,
        room_id: str,
        instance_id: str,
        price: int,
        title: str,
        description: str = "",
    ) -> ArtListing:
        self.housing.require_owned_room(account, room_id)
        if isinstance(price, bool) or not isinstance(price, int) or not ART_PRICE_MIN <= price <= ART_PRICE_MAX:
            raise ValueError(f"Set a price from {ART_PRICE_MIN} to {ART_PRICE_MAX} Bops.")
        clean_title = " ".join(str(title).split())
        clean_description = " ".join(str(description).split())
        if not clean_title or len(clean_title) > MAX_LISTING_TITLE:
            raise ValueError(f"Give the piece a title of {MAX_LISTING_TITLE} characters or fewer.")
        if len(clean_description) > MAX_LISTING_DESCRIPTION:
            raise ValueError(f"Keep the description under {MAX_LISTING_DESCRIPTION} characters.")
        layout = self.layout.view(account, room_id)
        prop = next(
            (entry for entry in layout.get("props", []) if str(entry.get("id")) == instance_id),
            None,
        )
        if prop is None or str(prop.get("prop_id")) != WHITEBOARD_PROP_ID:
            raise ValueError("That whiteboard is not in this room.")
        surface = self.surfaces.get(room_id, instance_id, "whiteboard")
        if surface.locked:
            raise ValueError("Purchased art cannot be listed for sale.")
        if not surface.content.get("strokes") and not surface.content.get("texts"):
            raise ValueError("Draw something on the whiteboard before listing it.")
        with self.hub.locked() as connection:
            active = connection.execute(
                "SELECT 1 FROM world.tinytown_art_listings WHERE seller_account_id = ? AND status = 'active'",
                (account.id,),
            ).fetchall()
            same_source = connection.execute(
                """
                SELECT 1 FROM world.tinytown_art_listings
                WHERE source_room_id = ? AND source_instance_id = ? AND status = 'active'
                """,
                (room_id, instance_id),
            ).fetchone()
        if same_source is not None:
            raise ValueError("That whiteboard is already listed.")
        if len(active) >= MAX_ART_LISTINGS:
            raise ValueError(f"You can have at most {MAX_ART_LISTINGS} pieces for sale at once.")
        listing = ArtListing(
            listing_id=f"artlisting:{uuid.uuid4().hex}",
            seller_id=account.id,
            source_room_id=room_id,
            source_instance_id=instance_id,
            title=clean_title,
            description=clean_description,
            price=int(price),
            surface=json.loads(json.dumps(surface.content)),
            status="active",
            created_at=utc_now().isoformat(),
        )
        with self.hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO world.tinytown_art_listings (
                    listing_id, seller_account_id, source_room_id, source_instance_id,
                    title, description, price, surface_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    listing.listing_id, listing.seller_id, listing.source_room_id,
                    listing.source_instance_id, listing.title, listing.description,
                    listing.price, json.dumps(listing.surface), listing.created_at,
                    listing.created_at,
                ),
            )
        return listing

    def withdraw(self, account: object, listing_id: str) -> ArtListing:
        listing = self._listing(listing_id)
        if listing is None or listing.seller_id != account.id:
            raise ValueError("That listing is not yours.")
        if listing.status != "active":
            raise ValueError("That listing is no longer active.")
        with self.hub.transaction() as connection:
            connection.execute(
                "UPDATE world.tinytown_art_listings SET status = 'withdrawn', updated_at = ? WHERE listing_id = ?",
                (utc_now().isoformat(), listing_id),
            )
        return self._listing(listing_id) or listing

    def purchased(self, account: object) -> list[dict[str, object]]:
        with self.hub.locked() as connection:
            rows = connection.execute(
                """
                SELECT l.*, s.surface_json AS sale_surface_json
                FROM world.tinytown_art_sales s
                JOIN world.tinytown_art_listings l ON l.listing_id = s.listing_id
                WHERE s.buyer_account_id = ?
                ORDER BY s.created_at DESC
                """,
                (account.id,),
            ).fetchall()
        results = []
        for row in rows:
            listing = self._listing_from_row(row)
            try:
                surface = json.loads(row["sale_surface_json"])
            except (TypeError, ValueError, KeyError):
                surface = listing.surface
            payload = self.listing_payload(listing, account.id, owned=True)
            payload["surface"] = surface
            results.append(payload)
        return results

    def market_payload(self, account: object, room_id: str | None = None) -> dict[str, object]:
        account_record = self.profiles.get_account_by_id(account.id) or account
        current_floor = self.housing.current_floor(room_id) if room_id and self.housing.current_house(room_id) else None
        floors = [
            self.housing._floor_payload(floor, account.id, current_floor.id if current_floor else None)
            for floor in self.housing.floors.values()
        ]
        room_payload = None
        whiteboards = 0
        can_hang = False
        if room_id:
            house = self.housing.current_house(room_id)
            if house is not None and house.owner_account_id == account.id:
                view = self.layout.view(account, room_id)
                whiteboards = sum(
                    1 for prop in view.get("props", []) if str(prop.get("prop_id")) == WHITEBOARD_PROP_ID
                )
                room_payload = {
                    "id": room_id,
                    "label": self.world.rooms[room_id].label,
                    "house_id": house.house_id,
                    "house": self.housing.template_for(house).label,
                    "current_floor": current_floor.id if current_floor is not None else "",
                }
                can_hang = True
        return {
            "room": room_payload,
            "can_hang": can_hang,
            "floors": floors,
            "art": [art_payload(piece) for piece in ART_PIECES],
            "unlocked_art": [
                piece.id for piece in ART_PIECES if self.housing.is_unlocked(account.id, "art", piece.id)
            ],
            "whiteboards": whiteboards,
            "max_whiteboards": MAX_WHITEBOARD_PROPS,
            "listings": self.active_listings(account.id),
            "purchased_listings": self.purchased(account),
            "my_listings": self.my_listings(account),
            "sellables": self.sellables(account),
            "max_listings": MAX_ART_LISTINGS,
            "wallet": int(account_record.bops),
        }

    def _wall_slot(self, props: list[dict[str, object]]) -> tuple[float, float]:
        whiteboards = [prop for prop in props if str(prop.get("prop_id")) == WHITEBOARD_PROP_ID]
        used_x = {
            round(float(prop.get("position", [0.0])[0]), 1)
            for prop in whiteboards
            if isinstance(prop.get("position"), list) and prop.get("position")
        }
        return next(
            (slot for slot in WHITEBOARD_SLOTS if round(slot[0], 1) not in used_x),
            WHITEBOARD_SLOTS[len(whiteboards) % len(WHITEBOARD_SLOTS)],
        )

    def _install_copy(
        self,
        connection: sqlite3.Connection,
        buyer: object,
        room_id: str,
        listing: ArtListing,
        surface_content: dict[str, object],
    ) -> tuple[str, int, dict[str, object]]:
        row = connection.execute(
            "SELECT props_json, environment_json, layout_revision FROM world.room_states WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            raise ValueError("The room layout is not ready yet.")
        try:
            props = json.loads(row["props_json"])
            environment = json.loads(row["environment_json"]) or {}
        except (TypeError, ValueError):
            props, environment = [], {}
        if not isinstance(props, list):
            props = []
        if not isinstance(environment, dict):
            environment = {}
        whiteboards = [prop for prop in props if str(prop.get("prop_id")) == WHITEBOARD_PROP_ID]
        if len(whiteboards) >= MAX_WHITEBOARD_PROPS:
            raise ValueError(
                f"This room already has {MAX_WHITEBOARD_PROPS} pieces on the walls. "
                "Make space before hanging another."
            )
        x, y = self._wall_slot(props)
        instance_id = f"custom:{uuid.uuid4()}"
        props.append(
            {
                "id": instance_id,
                "prop_id": WHITEBOARD_PROP_ID,
                "position": [x, y, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": 0.9,
                "locked": False,
            }
        )
        revision = self.world_state.write_room_layout(
            connection,
            room_id,
            props,
            environment,
            expected_revision=int(row["layout_revision"]),
        )
        surface = self.surfaces.install_whiteboard(
            room_id,
            instance_id,
            buyer.id,
            surface_content,
            locked=True,
            connection=connection,
        )
        return instance_id, revision, surface.serialize()

    def _layout_event(self, room_id: str, revision: int) -> dict[str, object]:
        return LayoutUpdate(
            room_id=room_id,
            revision=revision,
            props=[
                self.layout._serialize_instance(room_id, instance)
                for instance in self.layout.effective_props(room_id)
            ],
            environment=self.layout.visual_environment(room_id),
        ).event()

    def buy(self, account: object, room_id: str, listing_id: str) -> MarketPurchase:
        self.housing.require_owned_room(account, room_id)
        with self.hub.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM world.tinytown_art_listings WHERE listing_id = ? AND status = 'active'",
                (listing_id,),
            ).fetchone()
            if row is None:
                raise ValueError("That piece is no longer for sale.")
            listing = self._listing_from_row(row)
            if listing.seller_id == account.id:
                raise ValueError("You cannot buy your own artwork.")
            buyer = self.profiles.get_account_by_id(account.id)
            seller = self.profiles.get_account_by_id(listing.seller_id)
            if buyer is None or seller is None:
                raise ValueError("One of the accounts on this sale no longer exists.")
            existing = connection.execute(
                "SELECT 1 FROM world.tinytown_art_sales WHERE listing_id = ? AND buyer_account_id = ?",
                (listing_id, account.id),
            ).fetchone()
            if existing is not None:
                raise ValueError("You already own this print. Hang another copy from the gallery.")
            if buyer.bops < listing.price:
                raise ValueError(f"You need {listing.price - buyer.bops} more Bops for that print.")
            try:
                instance_id, revision, surface = self._install_copy(
                    connection, buyer, room_id, listing, listing.surface
                )
                connection.execute(
                    """
                    INSERT INTO world.tinytown_art_sales (
                        sale_id, listing_id, buyer_account_id, seller_account_id,
                        price, surface_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"artsale:{uuid.uuid4().hex}", listing.listing_id, buyer.id,
                        seller.id, listing.price, json.dumps(listing.surface),
                        utc_now().isoformat(),
                    ),
                )
                self.profiles.update_progress(connection, buyer, bops=buyer.bops - listing.price)
                self.profiles.update_progress(connection, seller, bops=seller.bops + listing.price)
            except sqlite3.IntegrityError as exc:
                raise ValueError("That print was already purchased.") from exc
        return MarketPurchase(
            message=f"“{listing.title}” is now hanging in {self.world.rooms[room_id].label}.",
            listing=self.listing_payload(listing, account.id, owned=True),
            layout_event=self._layout_event(room_id, revision),
            surface_event={
                "type": "room.prop.surface",
                "room_id": room_id,
                "prop_id": instance_id,
                "surface": surface,
            },
            bops_spent=listing.price,
        )

    def hang_owned(self, account: object, room_id: str, listing_id: str) -> MarketPurchase:
        self.housing.require_owned_room(account, room_id)
        with self.hub.transaction() as connection:
            row = connection.execute(
                """
                SELECT l.*, s.surface_json AS sale_surface_json
                FROM world.tinytown_art_sales s
                JOIN world.tinytown_art_listings l ON l.listing_id = s.listing_id
                WHERE s.listing_id = ? AND s.buyer_account_id = ?
                """,
                (listing_id, account.id),
            ).fetchone()
            if row is None:
                raise ValueError("You do not own that print.")
            listing = self._listing_from_row(row)
            try:
                surface_content = json.loads(row["sale_surface_json"])
            except (TypeError, ValueError, KeyError):
                surface_content = listing.surface
            if not isinstance(surface_content, dict):
                surface_content = listing.surface
            buyer = self.profiles.get_account_by_id(account.id)
            if buyer is None:
                raise ValueError("That account no longer exists.")
            instance_id, revision, surface = self._install_copy(
                connection, buyer, room_id, listing, surface_content
            )
        return MarketPurchase(
            message=f"Another copy of “{listing.title}” is hanging.",
            listing=self.listing_payload(listing, account.id, owned=True),
            layout_event=self._layout_event(room_id, revision),
            surface_event={
                "type": "room.prop.surface",
                "room_id": room_id,
                "prop_id": instance_id,
                "surface": surface,
            },
            bops_spent=0,
        )
