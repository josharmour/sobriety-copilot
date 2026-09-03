require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
if runner_target
  runner_target.build_configurations.each do |config|
    config.build_settings['CODE_SIGN_ENTITLEMENTS'] = 'Runner/Runner.entitlements'
  end
end

widget_target = project.targets.find { |t| t.name == 'SobrietyWidgets' }
if widget_target
  widget_target.build_configurations.each do |config|
    config.build_settings['CODE_SIGN_ENTITLEMENTS'] = 'SobrietyWidgets/SobrietyWidgets.entitlements'
  end
end

project.save
puts "Successfully configured CODE_SIGN_ENTITLEMENTS for Runner and SobrietyWidgets"
