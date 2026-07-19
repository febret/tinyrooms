from tinyrooms.user import User


class _FakeRoom:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.users = {}

    def add_user(self, user_obj: User):
        self.users[user_obj.username] = user_obj
        user_obj.room = self


class _FakeWorld:
    def __init__(self):
        self.ws_id = "home"
        self.rooms = {
            "DEFAULT_ROOM": _FakeRoom("DEFAULT_ROOM"),
            "playroom": _FakeRoom("playroom"),
        }
        self.default_room = self.rooms["DEFAULT_ROOM"]
        self.peeps = {}
        self.objs = {}


def test_join_world_restores_saved_room_and_position():
    world = _FakeWorld()
    state = {
        "last_world_id": "home",
        "last_room_id": "playroom",
        "last_x": 44,
        "last_y": 55,
    }
    user_obj = User("it_restore_room", "sid_restore_room", world, persisted_state=state)

    assert user_obj.room is world.rooms["playroom"]
    assert user_obj.peep.x == 44
    assert user_obj.peep.y == 55


def test_join_world_falls_back_to_default_for_invalid_room():
    world = _FakeWorld()
    state = {
        "last_world_id": "home",
        "last_room_id": "missing_room",
        "last_x": 77,
        "last_y": 88,
    }
    user_obj = User("it_restore_fallback", "sid_restore_fallback", world, persisted_state=state)

    assert user_obj.room is world.default_room
    assert user_obj.peep.x == 77
    assert user_obj.peep.y == 88
