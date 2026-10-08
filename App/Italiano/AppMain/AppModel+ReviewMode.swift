import Foundation
import LearningCore
import Storage

// Review mode (task M6.10) reads the open pack through the app model: whether it is a dev pack, the file index
// for comments (`meta.review_files`) and the course outline with draft flags for the jump menu.

extension ReviewMode {
    /// Call once the app model is ready (MainTabs does). Without a pack, review mode stays off.
    func attach(to app: AppModel) async {
        guard let reader = app.reader else { return }
        let outlines = (try? await reader.courseOutline()) ?? []
        attach(
            isReleasePack: reader.meta.isRelease, index: ReviewFileIndex(metaJSON: reader.meta.reviewFilesJSON),
            menu: ReviewJumpMenu(outlines: outlines))
    }
}

extension AppModel {
    /// Loads a step for review mode and opens it exactly at the jump (docs/04: every step unlocked).
    func launch(review jump: ReviewJump, in review: ReviewMode) async throws(PackError) -> PlayerLaunch? {
        guard let launch = try await launch(step: jump.step) else { return nil }
        review.prepare(launch, at: jump)
        return launch
    }
}

extension AppModel.PlayerLaunch {
    /// Finishing a unit check scores it (`checkCompleted`, the result screen) for learners only. In review mode the
    /// content lead pages through the check, answered or not, so nothing is scored.
    @MainActor
    func scoresCheck(review: ReviewMode?) -> Bool {
        let reviewing = review?.isActive == true
        return kind == .check && !reviewing
    }
}
