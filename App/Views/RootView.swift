import SwiftData
import SwiftUI

/// Tabs on iPhone; a sidebar on iPad and Mac (HANDOFF.md 2: Read, Dictionary, Verbs, Remember, Listen).
struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Environment(\.scenePhase) private var scenePhase
    @State private var showOnboarding = false
    /// Each tab's navigation stack.
    @State private var paths: [AppTab: [Route]] = [:]
    /// Watched so the Remember badge follows reviews and new cards.
    @Query private var cards: [Card]
    @Query private var states: [ScheduleState]

    private var dueCount: Int {
        _ = (cards.count, states.count)
        return RememberStore(context: context, prefs: prefs, content: model.content).queue(now: .now).count
    }

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.selectedTab) {
            Tab("Read", systemImage: "doc.text", value: AppTab.read) {
                NavigationStack(path: path(.read)) { LibraryView().withRoutes() }
            }
            Tab("Dictionary", systemImage: "book", value: AppTab.dictionary) {
                NavigationStack(path: path(.dictionary)) { DictionaryView().withRoutes() }
            }
            Tab("Verbs", systemImage: "tablecells", value: AppTab.verbs) {
                NavigationStack(path: path(.verbs)) { VerbsHomeView().withRoutes() }
            }
            Tab("Remember", systemImage: "rectangle.on.rectangle", value: AppTab.remember) {
                NavigationStack(path: path(.remember)) { RememberView().withRoutes() }
            }
            .badge(dueCount)
            Tab("Listen", systemImage: "headphones", value: AppTab.listen) {
                NavigationStack(path: path(.listen)) { ListenView().withRoutes() }
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
            #if DEBUG
            await openFromLaunchArguments()
            #endif
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { maintain() }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSUbiquitousKeyValueStore.didChangeExternallyNotification)) { _ in
            prefs.reloadFromCloud()
        }
    }

    private func path(_ tab: AppTab) -> Binding<[Route]> {
        Binding(get: { paths[tab] ?? [] }, set: { paths[tab] = $0 })
    }

    #if DEBUG
    /// The screenshot UI test opens screens directly (UITestLaunch).
    private func openFromLaunchArguments() async {
        if UITestLaunch.seed {
            UITestLaunch.seedRemember(RememberStore(context: context, prefs: prefs, content: model.content), model: model)
        }
        if let tab = UITestLaunch.tab { model.selectedTab = tab }
        if let route = UITestLaunch.route {
            // Let the selected tab's NavigationStack appear before pushing onto it.
            try? await Task.sleep(for: .milliseconds(500))
            paths[model.selectedTab] = [route]
        }
    }
    #endif

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
