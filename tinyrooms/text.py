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
        out = f'{out} {end_text}'
    return out.strip()


def make_emote_text(emote_def: dict, user_label: str, refs: list, extra_text: str = '') -> tuple:
    """Generate (first_person, second_person, third_person) message strings for an emote.

    ``second_person`` is ``None`` when the emote has no ``second`` template for
    the current ref count, or when the selected template is ``null``.

    ``msg`` in the emote definition may be either a single dict or a list of
    dicts (multiple message sets), in which case one is chosen at random.
    """
    msg = emote_def.get('msg', {})
    if isinstance(msg, list):
        msg = random.choice(msg) if msg else {}

    def _coerce_list(val):
        if val is None:
            return []
        if isinstance(val, str):
            return [val]
        return list(val)

    first_variants = _coerce_list(msg.get('first', []))
    second_variants = _coerce_list(msg.get('second', []))
    third_variants = _coerce_list(msg.get('third', []))
    end_variants = _coerce_list(msg.get('end', []))

    ref_count = len(refs)
    end_text = random.choice(end_variants) if end_variants else ''

    def pick(variants, idx):
        if not variants:
            return None
        return variants[min(idx, len(variants) - 1)]

    first_tmpl = pick(first_variants, ref_count)
    second_tmpl = pick(second_variants, ref_count)
    third_tmpl = pick(third_variants, ref_count)

    first = _apply_placeholders(first_tmpl, user_label, refs, extra_text, end_text) if first_tmpl else None
    second = _apply_placeholders(second_tmpl, user_label, refs, extra_text, end_text) if second_tmpl else None
    third = _apply_placeholders(third_tmpl, user_label, refs, extra_text, end_text) if third_tmpl else None

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
