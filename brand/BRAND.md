# Brand

A small, fixed set of assets. Everything is SVG except the social card, which
GitHub needs as a raster.

| File | What it is | Where it goes |
|---|---|---|
| [`mark.svg`](mark.svg) | The mark alone, 100 x 100 | favicon, avatar, anything under 200px |
| [`lockup.svg`](lockup.svg) | Mark plus wordmark | README header, slides, docs |
| [`social.svg`](social.svg) | 1280 x 640 source | edit this, then re-export |
| [`social.png`](social.png) | 1280 x 640 export | Settings -> General -> Social preview |

## The mark

Two brackets facing each other across a chalk line.

The chalk line is the mirror: the rule an acceptance is held to. The magenta
brackets are the offer and the acceptance. Each is the exact reflection of the
other across the line, and only because they mirror do the two open shapes read
as one closed one. Move a single stroke on either side and the pair stops
closing, which is the mirror-image rule drawn: a reply that changes any term is
not an acceptance. A handshake or a signature would be describing a verdict;
this describes the test the contract applies.

Built on a 100 x 100 grid. Stroke weight 8, round caps and joins, corner radius
18. The mirror is chalk at 4, opacity 0.85, thinner than the brackets and in a
different colour, so it reads as the rule rather than as a third bracket.

- **Clear space:** half the mark height on every side.
- **Smallest size:** 18px alone, 24px locked to the wordmark. The gap between
  each bracket and the mirror stays open.
- **Never:** a second hue, a gradient, an outline version, a drop shadow, or the
  brackets drawn unequal. Unequal, the mark says the opposite of what it means.

## Palette

| Token | Hex | Use |
|---|---|---|
| ink | `#0C0D10` | the mark's field, any dark surface |
| chalk | `#E8E6E1` | the wordmark, primary text, the mirror. Never pure white |
| accent | `#C567D4` | the mark, one primary action, one live state |
| muted | `#9AA0A8` | secondary text |
| rule | `#232830` | hairlines and dividers |

One accent, used sparingly. On the social card it appears exactly three times:
the top bar, the mark, and the footer line.

The accent is distinct from its siblings on purpose: Crosscheck is violet
`#8B7CF6`, Tolerance green `#3DD68C`, Recant coral `#E0645C`, Ratchet amber
`#E0A23C`, Keystone cyan `#3DBFD6`, Accrue chartreuse `#A8D24A`, Quorum blue
`#5B8DEF`, Covenant rose `#E86A92`, and this one magenta `#C567D4`. Same grid,
same stroke language, same lockup geometry, different hue - so the set reads as
one hand without reading as one product.

## Type

**Inter**, weights 400 and 700, tracking tightened to -1.4 on the wordmark and
-2.6 at display size. Monospace for anything that is a value rather than a
sentence: `ui-monospace, SFMono-Regular, Menlo, monospace`. The wordmark is
always lowercase.

## Re-exporting the social card

```bash
pip install resvg_py
python -c "import resvg_py, pathlib; pathlib.Path('brand/social.png').write_bytes(bytes(resvg_py.svg_to_bytes(svg_path='brand/social.svg', width=1280, height=640)))"
```

resvg renders with the fonts installed on the machine, and falls back from
Inter to Helvetica Neue or Arial where Inter is missing, which is how the card
here was made.

Upload under **Settings -> General -> Social preview**. GitHub uses it whenever
a link to this repository is shared.

## Licence

MIT along with the rest of the repository. The name and mark identify this
specific primitive, so if you fork it and change what it does, change the name
too.
