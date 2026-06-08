class Peep:
    def __init__(self, peep_id, type, info, location_id: str = ''):
        self.peep_id = peep_id
        self.type = type
        self.info = info
        self.location_id = location_id
        self.inventory = {}
        # Populated by icons.preprocess_world_icons() at world-load time
        self._icon_def = None

    def id(self):
        return f"@peep:{self.peep_id}"