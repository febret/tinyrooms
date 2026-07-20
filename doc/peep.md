# Tinyrooms Peep Specification
Peeps are the tinyroom implementation of NPCs. They are displayed as character sprites and can interact with other users, peeps and the environment through behaviors and behavior scripts.

Peeps are used to implement all types of non-player characters, from simple creatures to merchants, quest givers, dialog characters and fully AI-controlled bots.

## Peep Definition
A Peep class has the following properties:
...

A Peep instance has the following properties:
...

Peeps classes live in yaml files in the `data/peeps` server directory and world `peeps` directory. Note the difference between a peep CLASS (ie a template for a peep including the behavior it will use), and a peep INSTANCE (ie an active instance in the world of a peep from a specific class, see tinyrooms/peep.py)

Peep classes are defined exclusively in yaml files. Peep instances can be added to room in world yaml files, but they are also serialized in the world state DB in their own `peeps` table (similar to the `objects` table)

## Peep Behavior