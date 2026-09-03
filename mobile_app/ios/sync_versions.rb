require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

project.targets.each do |target|
  target.build_configurations.each do |config|
    config.build_settings['CURRENT_PROJECT_VERSION'] = '22'
    config.build_settings['MARKETING_VERSION'] = '1.3.0'
  end
end

project.save
puts "Successfully synced CURRENT_PROJECT_VERSION=22 and MARKETING_VERSION=1.3.0 across all Xcode targets"
