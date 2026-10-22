# Output formats and singer styling

[Back to the README](../README.md) · [CLI reference](cli-reference.md) · [Browser editor](editor.md)

Savant can write two related lyric formats. They serve different needs, so choose the output your music player supports.

## LRC: line-timed lyrics

LRC stores a timestamp for each line. It is broadly supported and a good default when you want synchronized lyrics without word-by-word highlighting.

Example:

```text
[00:12.34]First lyric line
[00:15.20]Second lyric line
```

The usual output is `Song.lrc` next to the audio file. Use `--output PATH` to choose another location. When adjusting an existing LRC, Savant defaults to a separate `.adjusted.lrc` file so the original is not replaced.

## TTML: word-timed lyrics

TTML can carry word/character timing and additional singer/style metadata. Use `--word-level` or `--ttml-output PATH` to request a TTML sidecar. Compatible players can use word intervals for karaoke-style highlighting, but support and rendering vary by player.

LRC is still written as a compatibility fallback when word-level output is enabled. TTML output alone does not guarantee that a player will display word highlighting; check your player's supported format.

## Multi-singer and styling hints

For supported lyric files, a first-line role definition can define the default singer, a featured/italic singer, and a duet/group label. Example:

```text
[Forrest Nolan, *love interest*, **Forrest Nolan & love interest**]
Hi
*Hello*
**We are both speaking**
```

The unmarked line uses the default singer, `*...*` marks the featured part, and `**...**` marks the shared/duet part. These markers help Savant associate sections of the lyrics with named TTML agents when generating TTML output.

For custom singer IDs, colors, or styles, use `--singer-config PATH`; details and flags are in the [CLI reference](cli-reference.md). The project includes an [example duet lyric file](../examples/duet-lyrics.txt).

## Instrumental markers

With `--instrumental-cues`, Savant can add timestamped `♪` markers for longer lyric-free openings, gaps, or endings. Adjust the minimum gap with `--instrumental-threshold SECONDS`.

## Important limitations

- Savant aligns lyrics you provide. It does not generate the correct lyrics from audio.
- Word- or character-level highlight depends on support in the target player, not just on the fact that a TTML file exists.
- Backing vocals, heavy compression, live recordings, extended melisma, incorrect lyrics, and unusual pronunciation can reduce alignment quality. Review results before using them in a library.
