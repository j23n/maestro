# Word frequencies

`it-opensubtitles-2018.txt` holds the 20,000 most frequent Italian word forms in the OpenSubtitles 2018 corpus, one `form count` pair per line, most frequent first. It is the first 20,000 lines of `content/2018/it/it_50k.txt` from [FrequencyWords](https://github.com/hermitdave/FrequencyWords) at commit `525f9b560de45753a5ea01069454e72e9aa541c6`. The lists are licensed CC BY-SA 4.0, like the dictionary database they feed.

The content build turns form counts into a rank per lemma (`lemma.freq_rank`), and the level plans in `content/curriculum/` set each level's core vocabulary as a rank band. Subtitles are spoken, everyday Italian, which suits a reading app for learners, but the list also holds character names from films; those never link to a dictionary lemma.

To refresh it, take a newer commit of the same file and update the commit above.
