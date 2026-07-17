# Tinyrooms Room Specifications
A room in tinyrooms is like an extended chat room which contains objects, peeps (user or NCP controlled) and a set of 'props' (ie special objects that appear on the room background and can only be modified y the room owner).

In the client, a room is displayed as a stage, ie a canvas which displays the room+props as a background and has objects and characters (which can dynamically move) in the foreground.

## Room Implementation Notes
In the tinyroom server room logic is defined in tinyrooms/room.py
Among other things, a room is defined by a label, description and a set of props with their position and orientation. A room also has an owner, which is the user allow to modify the room props.

## Room Client UI
A room background and props are displayed in the client in the roomPanel section of the UI (see app.md). Objects and peeps present in the room are displayed in the foreground. 

### Object Manipulation
In the app, users are allowed to move the sprite for their own peep, plus any objects in the room. Things can be moved simply by drag/dropping them. Moves are synchronized across all clients (see the the Room Update Messages sections)

## Prop Definition
Props are defined similarly to things (see data/worlds/home/things.yaml): they have an image, description, label, etc. But they are defined and handled separately as they can only be edited by a room owner and can have some extra special properties that unlike things can modify gameplay.

## Prop and Object Display
Both props and objects have three distinct displays (specified as properties pointing to image or svg files in their yaml definition)
- 'icon' (a fixed 32x32 icon, used to display this entity in menus and inventories)
- 'img' (a custom size - max 128-x128 image used to display this entity in longer description views)
- 'sprite' (a 32x32 min, 64x64 max illustration used to show this object or prop in the room view)

### Room Stage and Foreground Objects
The room background and props are displayed directly on the room canvas, while the object / character sprites are displayed with a subtle background shadow (applied on the client via css) to separate them from the fixed room stage.


## Room Update Messages
The room panel in the client is updated when receiving `update_view` messages (see app/client.js socket.on("update_view", ...)). The view parameter of the message determines which part of the room panel is updated:
- 'header' updates the room description / status header
- 'room-stage' updates the room stage view, i.e. the room background / props / prop position and orientations
- 'room-object' updates a single room object, adding it, removing it or updating its display status (position, sprite, sprite effects). When an existing object moves, the move should be applied smoothly.
- 'room-exits' updates the view with the room exit buttons.
