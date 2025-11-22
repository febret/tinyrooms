import random

from . import world

def get_ref_label(ref, strip_article = False) -> str:
    """Get the label text for a reference, optionally stripping leading articles."""
    label = ref if isinstance(ref, str) else ref.label
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


def make_action_text(action_def: dict, user_label, refs, extra_text):
    action_text = action_def.get("action_text", [])
    target_text = action_def.get("target_text", [])
    if isinstance(target_text, str):
        target_text = [target_text]
    end_text = action_def.get("end_text", [])
    out_text = ""
    if len(refs) > 0 and len(target_text) > 0:
        out_text = target_text[min(len(refs)-1, len(target_text)-1)]
    out_text += f': {extra_text} '
    
    # Pick a random end text
    if isinstance(end_text, str):
        end_text = [end_text]
    if len(end_text) > 0:
        out_text += f" {random.choice(end_text)}"
        
    # Replace all $ placeholders with names of refs in msg, then find any left over
    # $- placeholders are the same as $ but with leading articles stripped
    for i, ref in enumerate(refs):
        out_text = out_text.replace(f"${i+1}", get_ref_label(ref))
        out_text = out_text.replace(f"$-{i+1}", get_ref_label(ref, strip_article=True))
    nothing_txt = ['nothing', 'no one', 'nobody', 'void', 'the ether']
    for n in range(len(refs)+1, 10):
        out_text = out_text.replace(f"${n}", random.choice(nothing_txt))
    
    # Replace $* with random tokens from all refs
    if "$*" in out_text:
        out_text = out_text.replace("$*", melt_ref_labels(refs))
    
    # Replace YAML-compatible << >> constructs with ref creation texts
    out_text = out_text.replace("<<", "[[@ ")
    out_text = out_text.replace(">>", " ]]")

    out_text1 = f"{action_text[0]} {out_text}"      
    out_text3 = f"{action_text[1]}:  {out_text}"
    out_text3 = out_text3.replace("$0", user_label)
    return out_text1, out_text3


def make_room_description_text(room, user):
    description = room.info.get('description', '')
    if room.objs:
        description += "\nYou see "
        obj_texts = []
        for o, od in room.objs.items():
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
