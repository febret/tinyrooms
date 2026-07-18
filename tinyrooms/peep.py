class Peep:
    def __init__(self, peep_id, type, info, location_id: str = ''):
        self.peep_id = peep_id
        self.type = type
        self.info = info
        self.location_id = location_id
        self.inventory = {}
        self.x = int(info.get('x', 32))
        self.y = int(info.get('y', 32))
        self.orientation = info.get('orientation', 'front')
        self.layer = int(info.get('layer', 1))
        self.z_order = int(info.get('z_order', 1))
        # Populated by icons.preprocess_world_assets() at world-load time
        self._display_assets = None

    @property
    def display_assets(self):
        return self._display_assets

    @display_assets.setter
    def display_assets(self, assets):
        self._display_assets = assets

    def id(self):
        return f"@peep:{self.peep_id}"

    def label(self):
        return self.info.get('label', self.peep_id)

    def description(self):
        return self.info.get('description', '')