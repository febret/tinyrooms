class Prop:
    def __init__(self, prop_instance_id: str, prop_id: str, info: dict, room_id: str):
        self.prop_instance_id = prop_instance_id
        self.prop_id = prop_id
        self.info = info
        self.room_id = room_id
        self.x = int(info.get('x', 0))
        self.y = int(info.get('y', 0))
        self.orientation = info.get('orientation', 'front')
        self.layer = int(info.get('layer', 0))
        self.z_order = int(info.get('z_order', 0))
        self.metadata = dict(info.get('metadata', {}))
        self._display_assets = None

    def id(self):
        return f"@prop:{self.prop_instance_id}"

    def label(self):
        return self.info.get('label', self.prop_instance_id)

    def description(self):
        return self.info.get('description', '')
