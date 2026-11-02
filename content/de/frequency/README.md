# Word frequencies (German)

`de-opensubtitles-2018.txt` holds the 20,000 most frequent German word forms in the OpenSubtitles 2018 corpus, one `form count` pair per line, most frequent first. It is the first 20,000 lines of `content/2018/de/de_50k.txt` from [FrequencyWords](https://github.com/hermitdave/FrequencyWords) at commit `525f9b560de45753a5ea01069454e72e9aa541c6`, the same commit as the Italian list. The lists are licensed CC BY-SA 4.0, like the dictionary database they feed.

The list is lower case, so nouns appear without their capital (*zeit*, not *Zeit*). The German build has to match forms to lemmas without regard to case before it sets each lemma's rank (`lemma.freq_rank`); the level plans in `content/de/curriculum/` set each level's core vocabulary as a rank band. Character names from films never link to a dictionary lemma.
