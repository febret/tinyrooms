from flask_socketio import emit, join_room, leave_room

from .user import User


class Room:
    # update_view payload contract:
    # - header: room metadata and owner capabilities
    # - room-stage: stage metadata, background, and full prop list
    # - room-object: per-entity upsert/remove deltas for peeps/objects
    # - room-exits: normalized room exit button definitions
    def __init__(self, room_id, info, owner_id: str = ''):
        self.room_id = room_id
        self.info = info
        self.users = {}
        self.ways = {}
        self.objs = {}
        self.props = {}
        self.peeps = {}
        self.owner_id = owner_id
        self.label_override = None
        self.description_override = None
        self.initialized = False
        self._z_counter = 10

    def id(self):
        return f"@room:{self.room_id}"

    def label(self):
        if self.label_override:
            return self.label_override
        return self.info.get('label', f"Room {self.room_id}")

    def short_description(self):
        return self.info.get('description', '')

    def is_owner(self, user: User):
        return bool(self.owner_id) and self.owner_id == user.username

    def can_user_move_peep(self, actor: User, target_username: str):
        if actor.username == target_username:
            return True
        return self.is_owner(actor)

    def can_user_edit_props(self, actor: User):
        # return True
        return self.is_owner(actor)

    def next_z(self):
        self._z_counter += 1
        return self._z_counter

    def add_user(self, user: User):
        self.users[user.username] = user
        self.peeps[user.username] = user.peep
        user.peep.location_id = self.id()
        user.peep.z_order = self.next_z()
        user.room = self  # type: ignore
        join_room(self.room_id, sid=user.sid)
        self.send_full_room_sync(user)

        for other in list(self.users.values()):
            if other.username != user.username:
                self.send_room_object_update(other, user.peep, change_type='upsert', entity_type='peep', owner_username=user.username)

    def remove_user(self, user: User):
        if user.username not in self.users:
            return
        del self.users[user.username]
        if user.username in self.peeps:
            del self.peeps[user.username]
        leave_room(self.room_id, sid=user.sid)
        emit('update_view', {
            'view': 'room-object',
            'change': 'remove',
            'entity': {'entity_type': 'peep', 'entity_id': user.username},
        }, room=self.room_id, namespace='/')
        user.room = None

    def send_text(self, message):
        emit('message', {'text': message}, room=self.room_id, namespace='/')  # type: ignore

    def send_full_room_sync(self, user: User):
        self.send_header_view(user)
        self.send_room_stage_view(user)
        for obj in self.objs.values():
            self.send_room_object_update(user, obj, change_type='upsert', entity_type='object')
        for uname, peep in self.peeps.items():
            self.send_room_object_update(user, peep, change_type='upsert', entity_type='peep', owner_username=uname)
        self.send_room_exits_view(user)

    def send_header_view(self, user: User):
        emit('update_view', {
            'view': 'header',
            'room_id': self.room_id,
            'label': self.label(),
            'short_description': self.short_description(),
            'status_indicators': [],
            'owner_id': self.owner_id,
            'is_room_owner': self.is_owner(user),
            'can_edit_props': self.can_user_edit_props(user),
        }, to=user.sid, namespace='/')

    def send_room_stage_view(self, user: User):
        stage_meta = self.info.get('stage', {})
        from .world import active_world

        world = active_world()
        emit('update_view', {
            'view': 'room-stage',
            'room_id': self.room_id,
            'stage': {
                'width': int(stage_meta.get('width', 256)),
                'height': int(stage_meta.get('height', 512)),
                'bounds': stage_meta.get('bounds', {}),
                'theme': stage_meta.get('theme', ''),
            },
            'background': self.info.get('image') or self.info.get('img', ''),
            'props': [self._serialize_prop(prop) for prop in self.props.values()],
            'prop_library': [self._serialize_prop_def(prop_id, prop_info, world.root_path) for prop_id, prop_info in sorted(world.prop_defs.items())],
            'can_edit_props': self.can_user_edit_props(user),
        }, to=user.sid, namespace='/')

    def send_room_exits_view(self, user: User):
        exits = []
        for way_id, way in self.ways.items():
            exits.append({
                'id': way_id,
                'label': way.label,
                'target_room_id': way.info.get('to', ''),
            })
        emit('update_view', {'view': 'room-exits', 'room_id': self.room_id, 'exits': exits}, to=user.sid, namespace='/')

    def send_room_object_update(self, user: User, entity, change_type='upsert', entity_type='object', owner_username=''):
        emit('update_view', {
            'view': 'room-object',
            'room_id': self.room_id,
            'change': change_type,
            'entity': self._serialize_foreground_entity(
                entity,
                entity_type=entity_type,
                owner_username=owner_username,
                is_self=(owner_username == user.username if entity_type == 'peep' else False),
            ),
        }, to=user.sid, namespace='/')

    def broadcast_room_object_update(self, entity, change_type='upsert', entity_type='object', owner_username=''):
        for room_user in self.users.values():
            self.send_room_object_update(room_user, entity, change_type=change_type, entity_type=entity_type, owner_username=owner_username)

    def _serialize_prop(self, prop):
        return {
            'prop_instance_id': prop.prop_instance_id,
            'prop_id': prop.prop_id,
            'label': prop.label(),
            'description': prop.description(),
            'display': dict(getattr(prop, '_display_assets', {}) or {}),
            'position': {
                'x': prop.x,
                'y': prop.y,
                'orientation': prop.orientation,
                'layer': prop.layer,
                'z_order': prop.z_order,
            },
            'metadata': dict(prop.metadata),
        }

    def _serialize_foreground_entity(self, entity, entity_type='object', owner_username='', is_self=False):
        entity_id = entity.obj_id if entity_type == 'object' else owner_username
        label = entity.label() if callable(getattr(entity, 'label', None)) else entity_type
        description = entity.description() if callable(getattr(entity, 'description', None)) else ''
        return {
            'entity_id': entity_id,
            'entity_type': entity_type,
            'owner_username': owner_username if entity_type == 'peep' else '',
            'label': label,
            'description': description,
            'display': dict(getattr(entity, '_display_assets', {}) or {}),
            'position': {
                'x': int(getattr(entity, 'x', 0)),
                'y': int(getattr(entity, 'y', 0)),
                'orientation': getattr(entity, 'orientation', 'front'),
                'layer': int(getattr(entity, 'layer', 0)),
                'z_order': int(getattr(entity, 'z_order', 0)),
            },
            'is_self': bool(is_self),
        }

    def _serialize_prop_def(self, prop_id: str, prop_info: dict, world_root_path):
        from .icons import build_display_assets

        info = dict(prop_info or {})
        display = build_display_assets(info, world_root_path)
        return {
            'prop_id': prop_id,
            'label': info.get('label', prop_id),
            'description': info.get('description', ''),
            'display': display,
            'metadata': dict(info.get('metadata', {}) or {}),
        }


class Way:
    def __init__(self, way_id, info):
        self.way_id = way_id
        self.info = info
        self.label = info.get('label', '')
