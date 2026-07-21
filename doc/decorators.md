# Tinyrooms Sprite Decorators
Decorators are combinations of sprites and visual modifiers that can be applied to objects, peeps and props in the tinyrooms app.

An entity (object, peep, prop) can have more than one decorator applied to it. decorator effects keep running until a decorator is removed. Decorator effects take precedence based on the order in which they are applied, except for sprites, which are stacked instead of replaced with the last one.

decorators are defined in yaml files under data/decos and in the decos directory of the loaded world. Decorators cannot be redefined or overwritten in the worldstate db.

A decorator can  be referenced as:

A decorator is defined by:
- a unique (within the file) decorator id
- sprite: an optional sprite reference (including animation) for a sprite to display as part of this decorator
- glow: a glow intensity and color to apply to the underlying entity sprite
- animation: optional animations such as wobble, spin, pulse, to apply to the underlying entity sprite