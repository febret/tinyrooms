from . import decorators as decorator_module


class Object:
    def __init__(self, obj_id, thing_id, info, location_id: str, owner_id: str = ''):
        self.obj_id = obj_id
        self.thing_id = thing_id
        self.owner_id = owner_id
        self.info = info
        self.label_override = None
        self.description_override = None
        self.location_id = location_id
        self.contents = []
        self.x = int(info.get('x', 16))
        self.y = int(info.get('y', 16))
        self.orientation = info.get('orientation', 'front')
        self.layer = int(info.get('layer', 0))
        self.z_order = int(info.get('z_order', 0))
        self.decorators = decorator_module.normalize_decorator_list(info.get('decorators', []))
        # Populated by icons.preprocess_world_assets() at world-load time
        self._display_assets = None

    def id(self):
        return f"@obj:{self.obj_id}"

    def label(self):
        if self.label_override:
            return self.label_override
        return self.info.get('label', f"Object {self.obj_id}")

    def description(self):
        if self.description_override:
            return self.description_override
        return self.info.get('description', '')
