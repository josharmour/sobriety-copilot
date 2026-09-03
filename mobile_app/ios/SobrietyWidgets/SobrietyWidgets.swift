import WidgetKit
import SwiftUI

// MARK: - Shared Timeline Entry

struct SobrietyEntry: TimelineEntry {
    let date: Date
    let daysSober: Int
    let nextMilestoneLabel: String
    let daysToNextMilestone: Int
    let discreet: Bool
    let streakCount: Int
    let dailyTitle: String
    let dailyBody: String
    let dailySource: String
}

// MARK: - Timeline Provider

struct SobrietyTimelineProvider: TimelineProvider {
    typealias Entry = SobrietyEntry

    let appGroupId = "group.com.sobrietycopilot.app"

    func placeholder(in context: Context) -> SobrietyEntry {
        SobrietyEntry(
            date: Date(),
            daysSober: 92,
            nextMilestoneLabel: "6 months",
            daysToNextMilestone: 88,
            discreet: false,
            streakCount: 14,
            dailyTitle: "A Design for Living",
            dailyBody: "We are not cured of alcoholism. What we really have is a daily reprieve contingent on the maintenance of our spiritual condition.",
            dailySource: "Alcoholics Anonymous, p. 85"
        )
    }

    func getSnapshot(in context: Context, completion: @escaping (SobrietyEntry) -> Void) {
        completion(loadEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SobrietyEntry>) -> Void) {
        let entry = loadEntry()
        let calendar = Calendar.current
        let nextMidnight = calendar.startOfDay(for: calendar.date(byAdding: .day, value: 1, to: Date()) ?? Date())
        let timeline = Timeline(entries: [entry], policy: .after(nextMidnight))
        completion(timeline)
    }

    private func loadEntry() -> SobrietyEntry {
        let groupDefaults = UserDefaults(suiteName: appGroupId)
        let standardDefaults = UserDefaults.standard

        // Check group defaults then fallback to standard defaults
        let dateIso = groupDefaults?.string(forKey: "sobriety_date")
            ?? standardDefaults.string(forKey: "sobriety_date")
            ?? standardDefaults.string(forKey: "flutter.sobriety_date")

        let discreet = groupDefaults?.bool(forKey: "sobriety_discreet")
            ?? standardDefaults.bool(forKey: "sobriety_discreet")

        let streak = groupDefaults?.integer(forKey: "sobriety_streak")
            ?? standardDefaults.integer(forKey: "sobriety_streak")

        let title = groupDefaults?.string(forKey: "daily_title")
            ?? standardDefaults.string(forKey: "daily_title")
            ?? "A Design for Living"

        let body = groupDefaults?.string(forKey: "daily_body")
            ?? standardDefaults.string(forKey: "daily_body")
            ?? "We are not cured of alcoholism. What we really have is a daily reprieve contingent on the maintenance of our spiritual condition."

        let source = groupDefaults?.string(forKey: "daily_source")
            ?? standardDefaults.string(forKey: "daily_source")
            ?? "Alcoholics Anonymous, p. 85"

        let days = calculateDaysSince(dateIso: dateIso)
        let (daysToTarget, milestoneLabel) = nextMilestone(days: days)

        return SobrietyEntry(
            date: Date(),
            daysSober: days,
            nextMilestoneLabel: milestoneLabel,
            daysToNextMilestone: daysToTarget,
            discreet: discreet,
            streakCount: streak,
            dailyTitle: title,
            dailyBody: body,
            dailySource: source
        )
    }

    private func calculateDaysSince(dateIso: String?) -> Int {
        guard let dateIso = dateIso, !dateIso.isEmpty else { return 0 }
        
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        
        var parsedDate: Date?
        let formats = ["yyyy-MM-dd", "yyyy-MM-dd'T'HH:mm:ss.SSSZ", "yyyy-MM-dd'T'HH:mm:ssZ", "yyyy-MM-dd'T'HH:mm:ss"]
        for fmt in formats {
            formatter.dateFormat = fmt
            if let d = formatter.date(from: dateIso) {
                parsedDate = d
                break
            }
        }
        
        guard let startDate = parsedDate else { return 0 }

        let calendar = Calendar.current
        let start = calendar.startOfDay(for: startDate)
        let today = calendar.startOfDay(for: Date())
        let components = calendar.dateComponents([.day], from: start, to: today)
        return max(0, components.day ?? 0)
    }

    private func nextMilestone(days: Int) -> (Int, String) {
        let milestones: [(days: Int, label: String)] = [
            (1, "24 hours"), (7, "1 week"), (14, "2 weeks"), (30, "30 days"),
            (60, "60 days"), (90, "90 days"), (180, "6 months"), (270, "9 months"),
            (365, "1 year"), (545, "18 months"), (730, "2 years")
        ]
        for m in milestones {
            if days < m.days {
                return (m.days - days, m.label)
            }
        }
        let years = (days / 365) + 1
        let targetDays = years * 365
        return (targetDays - days, "\(years) years")
    }
}

// MARK: - Sobriety Counter Widget View

struct SobrietyCounterWidgetEntryView: View {
    var entry: SobrietyTimelineProvider.Entry
    @Environment(\.widgetFamily) var family

    var body: some View {
        switch family {
        case .systemSmall:
            smallCounterView
        case .systemMedium:
            mediumCounterView
        case .accessoryCircular:
            circularAccessoryView
        case .accessoryRectangular:
            rectangularAccessoryView
        case .accessoryInline:
            inlineAccessoryView
        default:
            smallCounterView
        }
    }

    private var smallCounterView: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(entry.discreet ? "SOBRIETY" : "DAYS SOBER")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                    .tracking(1.2)
                Spacer()
                if entry.streakCount > 0 {
                    HStack(spacing: 2) {
                        Image(systemName: "flame.fill")
                            .font(.system(size: 9))
                            .foregroundColor(.orange)
                        Text("\(entry.streakCount)")
                            .font(.system(size: 10, weight: .bold, design: .rounded))
                            .foregroundColor(.orange)
                    }
                }
            }

            Spacer()

            Text("\(entry.daysSober)")
                .font(.system(size: entry.daysSober > 999 ? 34 : 42, weight: .black, design: .rounded))
                .foregroundColor(.white)
                .minimumScaleFactor(0.7)

            if !entry.discreet {
                Text("\(entry.daysToNextMilestone)d to \(entry.nextMilestoneLabel)")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(Color(red: 0.58, green: 0.64, blue: 0.72))
                    .lineLimit(1)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(red: 0.08, green: 0.11, blue: 0.15))
    }

    private var mediumCounterView: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.discreet ? "SOBRIETY TRACKER" : "DAYS SOBER")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                    .tracking(1.2)

                Text("\(entry.daysSober)")
                    .font(.system(size: 44, weight: .black, design: .rounded))
                    .foregroundColor(.white)

                Text("One day at a time")
                    .font(.system(size: 11, weight: .medium).italic())
                    .foregroundColor(Color(red: 0.58, green: 0.64, blue: 0.72))
            }

            Divider()
                .background(Color.white.opacity(0.12))

            VStack(alignment: .leading, spacing: 10) {
                if entry.streakCount > 0 {
                    HStack(spacing: 5) {
                        Image(systemName: "flame.fill")
                            .foregroundColor(.orange)
                        Text("\(entry.streakCount) Day Check-in Streak")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.white)
                    }
                }

                if !entry.discreet {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Next Milestone")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundColor(Color(red: 0.45, green: 0.52, blue: 0.60))
                        Text("\(entry.daysToNextMilestone) days until \(entry.nextMilestoneLabel)")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Color(red: 0.85, green: 0.88, blue: 0.92))
                    }
                }
            }
            Spacer()
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.08, green: 0.11, blue: 0.15))
    }

    private var circularAccessoryView: some View {
        Gauge(value: Double(entry.daysSober % 30), in: 0...30) {
            Text("d")
        } currentValueLabel: {
            Text("\(entry.daysSober)")
                .font(.system(size: 14, weight: .bold, design: .rounded))
        }
        .gaugeStyle(.accessoryCircular)
    }

    private var rectangularAccessoryView: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(entry.discreet ? "Sobriety" : "Days Sober")
                .font(.system(size: 9, weight: .bold))
            Text("\(entry.daysSober) Days")
                .font(.system(size: 16, weight: .bold, design: .rounded))
            if !entry.discreet {
                Text("Next: \(entry.nextMilestoneLabel)")
                    .font(.system(size: 9))
                    .foregroundColor(.secondary)
            }
        }
    }

    private var inlineAccessoryView: some View {
        Text(entry.discreet ? "Day \(entry.daysSober)" : "🏆 \(entry.daysSober) Days Sober")
    }
}

// MARK: - Daily Reflection Widget View

struct DailyReflectionWidgetEntryView: View {
    var entry: SobrietyTimelineProvider.Entry
    @Environment(\.widgetFamily) var family

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("DAILY REFLECTION")
                    .font(.system(size: 9, weight: .bold, design: .rounded))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                    .tracking(1.0)
                Spacer()
                Text(entry.date, style: .date)
                    .font(.system(size: 9, weight: .medium))
                    .foregroundColor(Color(red: 0.58, green: 0.64, blue: 0.72))
            }

            Text(entry.dailyTitle)
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .foregroundColor(.white)
                .lineLimit(1)

            Text(entry.dailyBody)
                .font(.system(size: 12, weight: .regular))
                .foregroundColor(Color(red: 0.80, green: 0.84, blue: 0.89))
                .lineSpacing(2)
                .lineLimit(family == .systemLarge ? 7 : 3)

            Spacer()

            if !entry.dailySource.isEmpty {
                Text(entry.dailySource)
                    .font(.system(size: 10, weight: .medium).italic())
                    .foregroundColor(Color(red: 0.45, green: 0.52, blue: 0.60))
                    .lineLimit(1)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(red: 0.08, green: 0.11, blue: 0.15))
    }
}

// MARK: - Widget Configurations

struct SobrietyCounterWidget: Widget {
    let kind: String = "SobrietyCounterWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SobrietyTimelineProvider()) { entry in
            SobrietyCounterWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Sobriety Counter")
        .description("Track your clean time and next recovery milestones.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryCircular,
            .accessoryRectangular,
            .accessoryInline
        ])
    }
}

struct DailyReflectionWidget: Widget {
    let kind: String = "DailyReflectionWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SobrietyTimelineProvider()) { entry in
            DailyReflectionWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Daily Reflection")
        .description("Ground your day with daily recovery readings and study passages.")
        .supportedFamilies([.systemMedium, .systemLarge])
    }
}

// MARK: - Widget Bundle

@main
struct SobrietyWidgetsBundle: WidgetBundle {
    var body: some Widget {
        SobrietyCounterWidget()
        DailyReflectionWidget()
    }
}
