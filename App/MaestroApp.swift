import SwiftData
import SwiftUI

@main
struct MaestroApp: App {
    @State private var model = AppModel()
    private let container = LearnerSchema.makeContainer()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(model.prefs)
        }
        .modelContainer(container)
        #if os(macOS)
        .defaultSize(width: 1180, height: 780)
        #endif

        #if os(macOS)
        Settings {
            NavigationStack { SettingsView() }
                .frame(minWidth: 480, minHeight: 520)
                .environment(model)
                .environment(model.prefs)
                .modelContainer(container)
        }
        #endif
    }
}
