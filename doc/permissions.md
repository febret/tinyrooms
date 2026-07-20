# Tinyrooms User Permissions
Users can be given special powers (specified in the data/users/<username>/profile.yaml in the 'powers' property)
that affect both gameplay and admin powers for them.

## Available Powers
- admin: can send admin commands to the server from the client
- realtor: can grant remove and modify ownership of rooms
- shapeshifter: can use the character editor at any time rather than on first login only.

## Admin commands
Admin commands start with the '/' character and are defined in console.py (run_admin_cmd). Users with the 'admin'
power can send server commands from their client.
