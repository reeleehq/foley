# Forced aligners

Weaving places a word-anchored sound (`on 'door'`) where the narrator says the word, so it needs word timings: forced alignment of the narration audio to its transcript. foley takes the aligner as a seam, `aligner=` on `foley.weave(...)` and `foley.score(...)`, and ships four.

| Aligner | How it runs | Install | Word accuracy | Footprint | Licence |
|---|---|---|---|---|---|
| `FakeAligner` (default when nothing else is installed) | in process | nothing | none: words spread evenly over the clip | none | MIT (foley) |
| `WhisperXAligner` (default when `foley[align]` is installed) | in process | `pip install 'foley[align]'` | about ±50 ms, but times what Whisper *heard*, not your transcript | torch + Whisper and wav2vec2 models, GBs | BSD-2 (whisperX) |
| `MFAAligner` | `mfa align_one` subprocess | conda (below) | the most accurate of the four on read speech; aligns your transcript | conda env ~1.3 GB plus ~200 MB of models per language (unpacked) | MIT code; the pretrained models carry their own licence (see each model card) |
| `AeneasAligner` | `python -m aeneas.tools.execute_task` subprocess | espeak + ffmpeg + `pip install aeneas` (below) | coarser (TTS + DTW, tens to a few hundred ms); aligns your transcript | small, any language espeak speaks | AGPL-3.0; foley runs it as a separate program and never imports it |

Pick MFA when placement must be tight and you can install conda; aeneas when you need a language MFA has no model for or a small footprint; WhisperX when you have no transcript worth trusting. MFA and aeneas align the transcript you give, so a word a recogniser would mishear is still timed, and the timeline holds your words as written: whatever the program does to the text (MFA lowercases, drops punctuation, splits `Smith's` into `smith 's`), foley maps its tokens back onto the transcript's words, so `on 'door'` anchors find them.

## Use one

```python
import foley
from foley.weave import MFAAligner, AeneasAligner

result = foley.score(text, audio="narration.wav", aligner=MFAAligner())
woven = foley.weave(
    "narration.wav",
    timeline,
    transcript=text,
    aligner=AeneasAligner(python="~/venvs/aeneas/bin/python"),
)
```

The run manifest records which aligner timed the words (`mfa`, `aeneas`, `whisperx`, `fake`). With no transcript every aligner returns no timings and speech-anchored sounds fall back to their absolute onsets.

## Montreal Forced Aligner

```bash
conda create -n mfa -c conda-forge montreal-forced-aligner
conda run -n mfa mfa model download acoustic english_mfa
conda run -n mfa mfa model download dictionary english_mfa
```

Then `MFAAligner(mfa="<conda prefix>/envs/mfa/bin/mfa")`, or plain `MFAAligner()` when that env is active. The env need not be active: MFA calls helper binaries (`fstcompile`) from its own `bin`, and foley puts that directory on the program's `PATH` (macOS and Linux; on Windows, run foley inside the activated env).

Other languages: download that language's models (`mfa model download acoustic french_mfa`, same for the dictionary) and pass `MFAAligner(models={"fr": ("french_mfa", "french_mfa")})`. A word missing from the dictionary (a made-up word, an accented loanword, a number written as digits) comes back from MFA as `<unk>`; foley gives that word the `<unk>`'s timing, which is coarser than a dictionary word's. Write numbers as words, or give MFA a G2P model (`extra_args=("--g2p_model_path", ...)`), for better timings there. `extra_args` passes any option to `mfa align_one`; `timeout=` bounds a run.

## aeneas

aeneas needs `espeak` and `ffmpeg` on the system and builds only against `numpy<2`, so give it its own virtualenv:

```bash
brew install espeak ffmpeg            # or: apt install espeak libespeak-dev ffmpeg
python3.10 -m venv ~/venvs/aeneas
~/venvs/aeneas/bin/pip install "numpy<2" "setuptools<70"
~/venvs/aeneas/bin/pip install --no-build-isolation aeneas
```

Then `AeneasAligner(python="~/venvs/aeneas/bin/python")`. The transcript goes to aeneas one word per line, so each word becomes one fragment. Languages are mapped to aeneas's ISO 639-3 codes (`en` → `eng`, …); add one with `languages={"sv": "swe"}`.

aeneas is AGPL, so foley never imports it: it runs as its own process on a temporary WAV and text file. Whether that suits your distribution is a question for your own licence review.

## Your own

Any object with `word_timeline(audio, sample_rate, *, transcript=None, language="en") -> [{"word", "start", "end"}, ...]` (seconds) is an aligner (`foley.weave.protocols.Aligner`). For another command-line aligner, `foley.weave.cli_aligners.run_cli_aligner` handles the temporary files, the subprocess, the errors and the mapping back onto the transcript; you supply the command line and a parser for its output. Give the class a `name` to have it recorded in the run manifest.
