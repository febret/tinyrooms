import random


def get_ref_label(ref, strip_article = False) -> str:
    """Get the label text for a reference, optionally stripping leading articles."""
    if isinstance(ref, str):
        label = ref
    else:
        raw = ref.label
        label = raw() if callable(raw) else raw
    if strip_article:
        articles = ["a ", "an ", "the "]
        for art in articles:
            if label.lower().startswith(art):
                label = label[len(art):]
                break
    return label


def melt_ref_labels(refs) -> str:
    all_tokens = [get_ref_label(r, strip_article=True).split() for r in refs]
    out_len = min(len(tokens) for tokens in all_tokens) if all_tokens else 0
    output = []
    for i in range(out_len + 1):
        position_tokens = [tokens[i] for tokens in all_tokens if len(tokens) > i]
        if position_tokens:
            output.append(random.choice(position_tokens))
    return ' '.join(output)


def _apply_placeholders(tmpl: str, user_label: str, refs: list, extra_text: str, end_text: str) -> str:
    """Substitute $0/$N/$*/<< >> placeholders in a template string."""
    out = str(tmpl)
    out = out.replace('$0', user_label)
    for i, ref in enumerate(refs):
        out = out.replace(f'${i + 1}', get_ref_label(ref))
        out = out.replace(f'$-{i + 1}', get_ref_label(ref, strip_article=True))
    nothing_txt = ['nothing', 'no one', 'nobody', 'void', 'the ether']
    for n in range(len(refs) + 1, 10):
        out = out.replace(f'${n}', random.choice(nothing_txt))
    if '$*' in out:
        out = out.replace('$*', melt_ref_labels(refs))
    out = out.replace('<<', '[[@ ')
    out = out.replace('>>', ' ]]')
    if extra_text:
        out = f'{out}: {extra_text}'
    if end_text:
        if end_text and end_text[0] in ".,!?;:":
            out = f"{out}{end_text}"
        else:
            out = f"{out} {end_text}"
    return out.strip()


def make_emote_text(
    emote_def: dict,
    user_label: str,
    refs: list,
    extra_text: str = '',
    msg_index: int = 0,
) -> tuple:
    """Generate (first_person, second_person, third_person) message strings for an emote.

    Emote ``msg`` is expected to be a list of message-definition dicts:
    ``{verb: [first, third], target: "$1", end: ["."]}``.
    ``msg_index`` selects the message definition (clamped to available entries).
    """
    msg_defs = emote_def.get('msg', [])
    if not isinstance(msg_defs, list) or not msg_defs:
        return None, None, None

    msg_def = msg_defs[min(max(msg_index, 0), len(msg_defs) - 1)] or {}

    verb = msg_def.get("verb", [])
    if isinstance(verb, str):
        verb = [verb]
    elif not isinstance(verb, list):
        verb = []

    first_verb = str(verb[0]) if len(verb) >= 1 else ""
    third_verb = str(verb[1]) if len(verb) >= 2 else first_verb

    target_ref = refs[0] if refs else None
    target_tmpl = str(msg_def.get("target", "$1"))
    target_text = f" {target_tmpl}" if target_ref and target_tmpl else ""

    end_variants = msg_def.get("end", ["."])
    if isinstance(end_variants, str):
        end_variants = [end_variants]
    elif not isinstance(end_variants, list):
        end_variants = ["."]
    end_text = str(random.choice(end_variants)) if end_variants else "."

    first_tmpl = f"{first_verb}{target_text}".strip() if first_verb else None
    third_tmpl = f"{third_verb}{target_text}".strip() if third_verb else None

    second_tmpl = None
    if target_ref is not None and third_tmpl:
        second_tmpl = third_tmpl.replace("$1", "you").replace("$-1", "you")

    effective_refs = [target_ref] if target_ref is not None else []
    first = _apply_placeholders(first_tmpl, user_label, effective_refs, extra_text, end_text) if first_tmpl else None
    second = _apply_placeholders(second_tmpl, user_label, effective_refs, extra_text, end_text) if second_tmpl else None
    third = _apply_placeholders(third_tmpl, user_label, effective_refs, extra_text, end_text) if third_tmpl else None

    return first, second, third


def make_room_description_text(room, user):
    description = room.info.get('description', '')
    if room.objs:
        # Objects with dedicated room sprites are shown on stage, not duplicated in text.
        text_objs = [(o, od) for o, od in room.objs.items() if not getattr(od, '_display_assets', None)]
        if text_objs:
            description += "\nYou see "
            obj_texts = []
            for o, od in text_objs:
                ol = od.info.get('label', '')
                obj_texts.append(f"[[@obj:{o} {ol} ]]")
            description += ', '.join(obj_texts)
    if room.ways:
        description += "\nYou can go "
    for w, wd in room.ways.items():
        wl = wd.info.get('label', '')
        description += f"[[.go@way:{w} {wl} ]]"        
        
    # Replace YAML-compatible << >> constructs with ref creation texts
    out_text = description
    out_text = out_text.replace("<<", "[[@ ")
    out_text = out_text.replace(">>", " ]]")
    return out_text
