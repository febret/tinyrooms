# make-image

`tools/make-image` is the unified image-generation tool used by tinyrooms.

## Usage

```powershell
python tools/make-image <path.png> --size <WxH> [--description TEXT | --descriptors-json JSON]
```

## Examples

Generate a 64x128 character-style image from descriptors:

```powershell
python tools/make-image C:\tmp\sprite.png --size 64x128 --descriptors-json "{\"hair_color\":\"black\",\"skin_color\":\"olive\",\"body_adjective\":\"athletic\",\"clothing\":\"cloak\",\"clothing_material_or_color\":\"dark linen\"}" --border-color "#6aa5ff" --glow-color "#7cb1ff"
```

Generate a 64x64 icon-style image from description text:

```powershell
python tools/make-image C:\tmp\icon.png --size 64x64 --description "small wooden chest with brass lock" --style "retro pixel-art inspired shading"
```

Generate a custom size:

```powershell
python tools/make-image C:\tmp\poster.png --size 256x256 --description "ornate compass rose"
```

## Options

- `--size WxH` output size in pixels (for example `64x64`, `64x128`, `256x256`)
- `--description TEXT` prompt text
- `--descriptors-json JSON` descriptor object JSON
- `--style TEXT` optional style hint
- `--border-color #RRGGBB` optional outline effect color
- `--glow-color #RRGGBB` optional glow effect color

## Notes

- Output must be a `.png` path.
- At least one of `--description` or `--descriptors-json` is required.
