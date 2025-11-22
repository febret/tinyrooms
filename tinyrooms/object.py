class Object:
    def __init__(self, obj_id, info):
        self.obj_id = obj_id
        self.info = info
        self.label = info.get('label', '')
        self.description = info.get('description', '')
        self.image = info.get('image', '')
        self.tags = info.get('tags', [])
        self.room = None
