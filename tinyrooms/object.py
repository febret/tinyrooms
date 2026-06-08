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
        # Populated by icons.preprocess_world_icons() at world-load time
        self._icon_def = None

    def id(self):
        return f"@obj:{self.obj_id}"

    def label(self):
        if self.label_override:
            return self.label_override
        return self.info.get('label', f"Object {self.obj_id}")
