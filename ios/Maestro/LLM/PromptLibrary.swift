// ⚠️ UNEXERCISED — compiles, but no prompt has been rendered for a real
// feedback call: gates closed.
//
// The prompts the app sends are the same ones the eval harness measures.
// `prompts/runtime/*.yaml` is the single source; `maestro-pack prompts`
// compiles it to `build/prompts.json`, which is bundled here. Rendering a
// prompt string inline in Swift would break that — the scorecard would
// then describe something the app doesn't send.

import Foundation

struct RuntimePrompt: Codable {
    let version: Int
    let system: String
    let template: String
    let defaults: [String: String]

    private enum CodingKeys: String, CodingKey { case version, system, template, defaults }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decode(Int.self, forKey: .version)
        system = try c.decode(String.self, forKey: .system)
        template = try c.decode(String.self, forKey: .template)
        // Defaults are authored as YAML scalars, so they arrive as ints as
        // often as strings; the template only ever interpolates text.
        let raw = try c.decodeIfPresent([String: JSONScalar].self, forKey: .defaults)
        defaults = (raw ?? [:]).mapValues(\.stringValue)
    }
}

/// A YAML/JSON scalar that could be a string, int or bool.
struct JSONScalar: Codable {
    let stringValue: String

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) { stringValue = s }
        else if let i = try? c.decode(Int.self) { stringValue = String(i) }
        else if let b = try? c.decode(Bool.self) { stringValue = String(b) }
        else { stringValue = "" }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(stringValue)
    }
}

enum PromptError: Error, LocalizedError {
    case bundleMissing
    case unknownTask(String)
    /// A placeholder nothing supplied. Rendering it literally would quietly
    /// degrade the prompt, so this fails loudly instead.
    case unresolved(task: String, names: [String])

    var errorDescription: String? {
        switch self {
        case .bundleMissing:
            return "prompts.json isn't bundled — run `maestro-pack prompts`"
        case .unknownTask(let task):
            return "no runtime prompt for \(task)"
        case .unresolved(let task, let names):
            return "\(task): nothing supplied \(names.joined(separator: ", "))"
        }
    }
}

struct PromptLibrary {
    private let prompts: [String: RuntimePrompt]

    init(bundle: Bundle = .main) throws {
        guard let url = bundle.url(forResource: "prompts", withExtension: "json"),
              let data = try? Data(contentsOf: url)
        else { throw PromptError.bundleMissing }
        prompts = try JSONDecoder().decode([String: RuntimePrompt].self, from: data)
    }

    func version(of task: String) -> Int? { prompts[task]?.version }

    /// The system + user prompt for a task, with `variables` substituted.
    /// Mirrors Python's `str.format`: `{name}` interpolates, `{{` and `}}`
    /// are literal braces — which the templates rely on, since every one of
    /// them specifies a JSON response shape.
    func render(
        task: String, variables: [String: String]
    ) throws -> (system: String, prompt: String) {
        guard let prompt = prompts[task] else { throw PromptError.unknownTask(task) }
        let values = prompt.defaults.merging(variables) { _, supplied in supplied }

        var out = ""
        var unresolved: [String] = []
        var rest = Substring(prompt.template)
        while let open = rest.firstIndex(of: "{") {
            out += rest[rest.startIndex ..< open]
            let afterOpen = rest.index(after: open)
            if afterOpen < rest.endIndex, rest[afterOpen] == "{" {
                out += "{"
                rest = rest[rest.index(after: afterOpen)...]
                continue
            }
            guard let close = rest[afterOpen...].firstIndex(of: "}") else {
                out += rest[open...]
                rest = rest[rest.endIndex...]
                break
            }
            let name = String(rest[afterOpen ..< close])
            if let value = values[name] {
                out += value
            } else {
                unresolved.append(name)
            }
            rest = rest[rest.index(after: close)...]
        }
        out += rest
        out = out.replacingOccurrences(of: "}}", with: "}")

        guard unresolved.isEmpty else {
            throw PromptError.unresolved(task: task, names: unresolved)
        }
        return (prompt.system, out)
    }
}
