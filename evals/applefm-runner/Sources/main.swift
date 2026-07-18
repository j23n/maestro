// ⚠️ UNTESTED SCAFFOLD (written off-Mac; expect to fix small API drift).
//
// Apple Foundation Models runner for the eval harness (plan §11.3).
// Protocol: one JSON object per line on stdin  {"system": "...", "prompt": "..."}
//           one JSON object per line on stdout {"output": "..."} | {"error": "..."}
// The harness invokes this via evals/harness/runners.py AppleFMRunner.

import Foundation
import FoundationModels

struct Request: Codable { let system: String; let prompt: String }
struct Reply: Codable { var output: String? = nil; var error: String? = nil }

func emit(_ reply: Reply) {
    let data = try! JSONEncoder().encode(reply)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

let model = SystemLanguageModel.default
guard model.availability == .available else {
    emit(Reply(error: "Foundation Models unavailable: \(model.availability)"))
    exit(1)
}

while let line = readLine(strippingNewline: true), !line.isEmpty {
    do {
        let request = try JSONDecoder().decode(Request.self, from: Data(line.utf8))
        let session = LanguageModelSession(instructions: request.system)
        let semaphore = DispatchSemaphore(value: 0)
        var reply = Reply()
        Task {
            do {
                let response = try await session.respond(to: request.prompt)
                reply.output = response.content
            } catch {
                reply.error = "\(error)"
            }
            semaphore.signal()
        }
        semaphore.wait()
        emit(reply)
    } catch {
        emit(Reply(error: "bad request: \(error)"))
    }
}
