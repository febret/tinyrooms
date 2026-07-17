# Tinyrooms Client Application
The tinyrooms client app lives in the app directory. It is served via Flask by the
tinyrooms server.

## UI Logical structure
All the ui structure lives in client.html and is divided in pages to handle the login / game / etc. phases of the app.

The client DOM (simplified) is:
- loginPage
-  mainPage (contains the main game UI)
    - statusPanel (shows the user status, connection status and buttons to control the overall game)
    - logPanel (shows the message log)
    - activityPanel (visible only when an activity like dialog, container/inventory interaction etc. is engaged. Its content depends on the activity type)
    - roomPanel (contains the room view, description and actions)
        - roomHeader (contains the room description, status indicators and buttons to interact with the room - like to see its full description)
        - roomCanvas (the canvas where the room items, users, background and props are displayed; see room.md for more information of how a room is defined/displayed)
        - roomExits (contains the buttons for the exits to the room - these can change for different rooms)
    - actionsPanel (contains the main UI for the user)
        - lookBox (a one line box showing the description of the last selected object/action/etc.)
        - actionPalette (contains the buttons for actions the user can execute. See section on the Action Palette for more information)
    
## The Action Palette
the action palette displays a set of up to 6 buttons showing actions the user can execute. The default six actions are:
- Look (NOTE: look is different from just clicking on an item and seeing its quick description on the lookBox. looking involves bringing up a more complex description in the activity panel, or, in the case of containers, opening them).
- Use/Interact/Talk
- Emote (opens a different set, swapping the action buttons with emote buttons. A 'back' action is available to go back to the previous set)
- Equip (opens activity panel showing the user character equipment and inventory)
- Self (opens activity panel with information on the user character)
- Extras (opens additional set of actions customizable by the user, currently empty)

## Activity Panel
The activity panel types are:
- Equip (shows the equipment and inventory of the user character)
- Look (shows extended / rich description of a selected item / character / etc)
- Self (shows extended information about the user character and status)
- Dialog (contains a rich description and a set of custom action buttons)

