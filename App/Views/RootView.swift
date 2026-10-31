import SwiftData
import SwiftUI

/// Tabs on iPhone; a sidebar on iPad and Mac (HANDOFF.md 2: Read, Dictionary, Verbs, Remember, Listen).
struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Environment(\.scenePhase) private var scenePhase
    @State private var showOnboarding = false

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.selectedTab) {
            Tab("Read", systemImage: "book", value: AppTab.read) {
                NavigationStack { LibraryView().withRoutes() }
            }
            Tab("Dictionary", systemImage: "character.book.closed", value: AppTab.dictionary) {
                NavigationStack { DictionaryView().withRoutes() }
            }
            Tab("Verbs", systemImage: "textformat.abc", value: AppTab.verbs) {
                NavigationStack { VerbsHomeView().withRoutes() }
            }
            Tab("Remember", systemImage: "rectangle.stack", value: AppTab.remember) {
                NavigationStack { RememberView().withRoutes() }
            }
            Tab("Listen", systemImage: "headphones", value: AppTab.listen) {
                NavigationStack { ListenView().withRoutes() }
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .sheet(isPresented: $showOnboarding) {
            OnboardingView { showOnboarding = false }
                .interactiveDismissDisabled()
        }
        .task {
            if !prefs.onboarded { showOnboarding = true }
            maintain()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { maintain() }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSUbiquitousKeyValueStore.didChangeExternallyNotification)) { _ in
            prefs.reloadFromCloud()
        }
    }

    /// After launch and whenever the app comes back: dedupe what sync brought in, then bring the
    /// local schedule up to date with the review logs.
    private func maintain() {
        let store = RememberStore(context: context, prefs: prefs, content: model.content)
        store.mergePass()
        store.rebuildAll()
    }
}

extension View {
    /// The destinations every tab's NavigationStack can show.
    func withRoutes() -> some View {
        navigationDestination(for: Route.self) { route in
            RouteView(route: route)
        }
    }
}

struct RouteView: View {
    let route: Route

    var body: some View {
        switch route {
        case .text(let id): ReaderView(textID: id)
        case .questions(let id): QuestionsView(textID: id)
        case .entry(let id): EntryView(lemmaID: id)
        case .verb(let id, let tag): VerbView(lemmaID: id, highlightTag: tag)
        case .grammar(let id): GrammarTopicView(topicID: id)
        case .grammarIndex: GrammarIndexView()
        case .settings: SettingsView()
        }
    }
}
