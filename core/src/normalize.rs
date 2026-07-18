//! Answer normalization for deterministic scoring.
//!
//! Deliberately conservative for Italian: accents are *preserved* (e / è
//! are different words), case and surrounding punctuation are not.
//! Tolerance beyond this (article dropping, clitic variants) belongs in the
//! pack's acceptable-answer lists, authored and curated — not in code.

/// Lowercase, trim, collapse internal whitespace, and strip punctuation
/// that carries no meaning in a typed answer.
pub fn normalize(s: &str) -> String {
    let stripped: String = s
        .chars()
        .map(|c| match c {
            // Curly and straight apostrophes are equivalent in typed input.
            '\u{2019}' | '\u{02BC}' => '\'',
            _ => c,
        })
        .filter(|c| !matches!(c, '.' | ',' | ';' | ':' | '!' | '?' | '"' | '«' | '»'))
        .collect();
    stripped
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::normalize;

    #[test]
    fn strips_case_whitespace_and_punctuation() {
        assert_eq!(normalize("  Ho  mangiato! "), "ho mangiato");
        assert_eq!(normalize("«Vorrei una pizza.»"), "vorrei una pizza");
    }

    #[test]
    fn preserves_accents() {
        assert_ne!(normalize("e"), normalize("è"));
        assert_eq!(normalize("Caffè"), "caffè");
    }

    #[test]
    fn unifies_apostrophes() {
        assert_eq!(normalize("un\u{2019}amica"), "un'amica");
    }
}
