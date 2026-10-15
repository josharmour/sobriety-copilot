require 'xcodeproj'
require 'yaml'

pubspec_path = File.expand_path('../pubspec.yaml', __dir__)
pubspec = YAML.load_file(pubspec_path)
version_str = pubspec['version'].to_s.strip
marketing_version, build_number = version_str.split('+')

project_path = File.expand_path('Runner.xcodeproj', __dir__)
project = Xcodeproj::Project.open(project_path)

project.targets.each do |target|
  target.build_configurations.each do |config|
    config.build_settings['CURRENT_PROJECT_VERSION'] = build_number
    config.build_settings['MARKETING_VERSION'] = marketing_version
  end
end

project.save
puts "Successfully synced CURRENT_PROJECT_VERSION=#{build_number} and MARKETING_VERSION=#{marketing_version} from pubspec.yaml across all Xcode targets"
