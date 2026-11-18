RUMO INSTAGRAM KIT

What this does
  Builds a pool of Instagram posts from rumopt.com (the 60 free grammar chapters and
  the 40 free graded stories): quizzes, slang in chat bubbles, textbook vs. real, the
  classic traps, examples, cheat sheets, the stories, words from the stories, plus
  faceless Reels with original music. It checks every Portuguese line and translation
  against the live site, and posts ONE post a day at 18:00 UK time (every other one a
  Reel) through Meta's own free Instagram API. Once a week it reads the results and
  gives the formats that work best a few more turns.

Where it runs
  On GitHub's free runner (Actions). Your laptop can be off. Cost: nothing.
  The Instagram key is in the repository's locked secret store (META_TOKEN), never in
  a file. The repository is public because Instagram fetches the slides from it.

If something goes wrong
  GitHub opens an issue and emails you. It says what happened and what to do
  (the same text as FAILED.txt). DONE.txt always shows the latest status.

By hand (Actions > Rumo Instagram > Run workflow)
  check      results report       trial on / trial off    trial Reels
  build      redraw the previews  status                  where things stand

Don't
  - edit posts.json by hand (the accuracy check refuses it)
  - make the repository private (Instagram can then no longer fetch the slides)

Fonts in assets/fonts: Bricolage Grotesque, Fraunces, Inter (SIL Open Font Licence,
licence texts included). The music is synthesised by rumo_music.py: no samples, no
third-party recordings. Video encoding uses ffmpeg from the imageio-ffmpeg package.
