//! Transcript alignment scoring for speaking exercises.
//!
//! The platform STT (SpeechAnalyzer on iOS) produces a transcript; this
//! scores it against the target text word-by-word: which target words were
//! said, which were missed, what was heard instead. Pure text computation —
//! it measures *what* was said, not how it sounded (pronunciation scoring
//! is the optional online tier behind its own interface).
//!
//! Standard edit-distance alignment (Needleman–Wunsch over words) with a
//! near-match tier so STT hiccups ("caffe" vs "caffè", one-letter slips on
//! longer words) count as hits rather than misses — the fairness lever
//! flagged in the Phase 0 speech spike.

use serde::Serialize;

use crate::normalize::normalize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, uniffi::Enum)]
#[serde(rename_all = "snake_case")]
pub enum WordStatus {
    /// Exact match after normalization.
    Matched,
    /// Close enough (small edit distance) — counts toward the score.
    Near,
    /// Something else was said in its place.
    Substituted,
    /// Target word not found in the transcript.
    Missed,
}

#[derive(Debug, Clone, Serialize, uniffi::Record)]
pub struct WordVerdict {
    pub target: String,
    pub status: WordStatus,
    /// What the transcript had at this position (for substituted/near).
    pub heard: Option<String>,
}

#[derive(Debug, Clone, Serialize, uniffi::Record)]
pub struct AlignmentResult {
    /// matched + near, over target word count. In [0, 1].
    pub score: f64,
    pub verdicts: Vec<WordVerdict>,
    /// Transcript words that matched nothing (insertions) — surfaced so
    /// the UI can show them, not scored against the learner.
    pub extra_words: Vec<String>,
}

/// Levenshtein distance capped at 3 (we only care about small distances).
fn edit_distance(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    let mut curr = vec![0usize; b.len() + 1];
    for i in 1..=a.len() {
        curr[0] = i;
        for j in 1..=b.len() {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            curr[j] = (prev[j] + 1).min(curr[j - 1] + 1).min(prev[j - 1] + cost);
        }
        std::mem::swap(&mut prev, &mut curr);
    }
    prev[b.len()]
}

/// Accent-blind comparison for near-matching only: STT often drops
/// accents; "caffe" for "caffè" is a hit, while scoring keeps e/è distinct
/// in *typed* answers (normalize.rs).
fn deaccent(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'à' | 'á' | 'â' => 'a',
            'è' | 'é' | 'ê' => 'e',
            'ì' | 'í' | 'î' => 'i',
            'ò' | 'ó' | 'ô' => 'o',
            'ù' | 'ú' | 'û' => 'u',
            other => other,
        })
        .collect()
}

fn word_similarity(target: &str, heard: &str) -> WordStatus {
    if target == heard {
        return WordStatus::Matched;
    }
    let (t, h) = (deaccent(target), deaccent(heard));
    if t == h {
        return WordStatus::Near;
    }
    // One slip allowed on words of 4+, two on 8+.
    let allowed = match t.chars().count() {
        0..=3 => 0,
        4..=7 => 1,
        _ => 2,
    };
    if allowed > 0 && edit_distance(&t, &h) <= allowed {
        WordStatus::Near
    } else {
        WordStatus::Substituted
    }
}

#[uniffi::export]
pub fn align_transcript(target: String, transcript: String) -> AlignmentResult {
    let target_words: Vec<String> = normalize(&target)
        .split_whitespace()
        .map(String::from)
        .collect();
    let heard_words: Vec<String> = normalize(&transcript)
        .split_whitespace()
        .map(String::from)
        .collect();

    let n = target_words.len();
    let m = heard_words.len();
    // Needleman–Wunsch: 0 = match/near, 1 = substitution, 1 = gap.
    let cost = |i: usize, j: usize| -> u32 {
        match word_similarity(&target_words[i], &heard_words[j]) {
            WordStatus::Matched => 0,
            WordStatus::Near => 0,
            _ => 1,
        }
    };
    let mut dp = vec![vec![0u32; m + 1]; n + 1];
    for (i, row) in dp.iter_mut().enumerate() {
        row[0] = i as u32;
    }
    for (j, cell) in dp[0].iter_mut().enumerate() {
        *cell = j as u32;
    }
    for i in 1..=n {
        for j in 1..=m {
            dp[i][j] = (dp[i - 1][j] + 1)
                .min(dp[i][j - 1] + 1)
                .min(dp[i - 1][j - 1] + cost(i - 1, j - 1));
        }
    }

    // Backtrace.
    let mut verdicts = vec![
        WordVerdict {
            target: String::new(),
            status: WordStatus::Missed,
            heard: None,
        };
        n
    ];
    let mut extra_words = Vec::new();
    let (mut i, mut j) = (n, m);
    while i > 0 || j > 0 {
        if i > 0 && j > 0 && dp[i][j] == dp[i - 1][j - 1] + cost(i - 1, j - 1) {
            let status = word_similarity(&target_words[i - 1], &heard_words[j - 1]);
            verdicts[i - 1] = WordVerdict {
                target: target_words[i - 1].clone(),
                status,
                heard: Some(heard_words[j - 1].clone()),
            };
            i -= 1;
            j -= 1;
        } else if i > 0 && (j == 0 || dp[i][j] == dp[i - 1][j] + 1) {
            verdicts[i - 1] = WordVerdict {
                target: target_words[i - 1].clone(),
                status: WordStatus::Missed,
                heard: None,
            };
            i -= 1;
        } else {
            extra_words.push(heard_words[j - 1].clone());
            j -= 1;
        }
    }
    extra_words.reverse();

    let hits = verdicts
        .iter()
        .filter(|v| matches!(v.status, WordStatus::Matched | WordStatus::Near))
        .count();
    AlignmentResult {
        score: if n == 0 { 0.0 } else { hits as f64 / n as f64 },
        verdicts,
        extra_words,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn perfect_reading_scores_one() {
        let r = align_transcript(
            "Vorrei un caffè, per favore.".into(),
            "vorrei un caffè per favore".into(),
        );
        assert_eq!(r.score, 1.0);
        assert!(r.extra_words.is_empty());
    }

    #[test]
    fn dropped_accents_and_small_slips_are_near_hits() {
        let r = align_transcript(
            "Vorrei una pizza margherita".into(),
            "vorrei una pizza margarita".into(), // STT slip on one letter
        );
        assert_eq!(r.score, 1.0);
        assert_eq!(r.verdicts[3].status, WordStatus::Near);

        let r = align_transcript("Il caffè è buono".into(), "il caffe e buono".into());
        // caffe~caffè near; "e" vs "è" is a 3-letter... 1-char word: accent-
        // blind equality makes it Near, not a miss.
        assert_eq!(r.score, 1.0);
    }

    #[test]
    fn missed_and_substituted_words_are_reported() {
        let r = align_transcript(
            "Ieri ho mangiato la pizza".into(),
            "ieri mangiato una pizza".into(),
        );
        // "ho" missed, "la"->"una" substituted, rest matched.
        assert!(r.score > 0.5 && r.score < 1.0);
        let missed: Vec<&str> = r
            .verdicts
            .iter()
            .filter(|v| v.status == WordStatus::Missed)
            .map(|v| v.target.as_str())
            .collect();
        assert_eq!(missed, vec!["ho"]);
        let subst: Vec<&str> = r
            .verdicts
            .iter()
            .filter(|v| v.status == WordStatus::Substituted)
            .map(|v| v.target.as_str())
            .collect();
        assert_eq!(subst, vec!["la"]);
    }

    #[test]
    fn short_words_do_not_fuzzy_match() {
        // "ho" vs "o" must not count as near (1-char words carry grammar).
        let r = align_transcript("ho fame".into(), "o fame".into());
        assert_eq!(r.verdicts[0].status, WordStatus::Substituted);
    }

    #[test]
    fn extra_words_surface_without_penalty() {
        let r = align_transcript("Buongiorno".into(), "ehm buongiorno".into());
        assert_eq!(r.score, 1.0);
        assert_eq!(r.extra_words, vec!["ehm"]);
    }

    #[test]
    fn empty_inputs() {
        assert_eq!(align_transcript("ciao".into(), "".into()).score, 0.0);
        assert_eq!(align_transcript("".into(), "ciao".into()).score, 0.0);
    }
}
