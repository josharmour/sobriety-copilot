require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

team_id = '87J32K9ZCC'

# 1. Add SobrietyWidgets target
widget_target = project.targets.find { |t| t.name == 'SobrietyWidgets' }
if widget_target.nil?
  widget_target = project.new_target(:app_extension, 'SobrietyWidgets', :ios, '16.0', project.products_group, :swift)
  
  # Create group & files
  widget_group = project.main_group.find_subpath('SobrietyWidgets', true)
  widget_group.set_source_tree('<group>')
  widget_group.set_path('SobrietyWidgets')
  
  swift_file = widget_group.new_file('SobrietyWidgets.swift')
  plist_file = widget_group.new_file('Info.plist')
  
  widget_target.source_build_phase.add_file_reference(swift_file)
  
  # Configure build settings
  widget_target.build_configurations.each do |config|
    config.build_settings['PRODUCT_NAME'] = 'SobrietyWidgets'
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'com.sobrietycopilot.app.SobrietyWidgets'
    config.build_settings['INFOPLIST_FILE'] = 'SobrietyWidgets/Info.plist'
    config.build_settings['DEVELOPMENT_TEAM'] = team_id
    config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
    config.build_settings['SWIFT_VERSION'] = '5.0'
    config.build_settings['TARGETED_DEVICE_FAMILY'] = '1,2'
    config.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '16.0'
    config.build_settings['GENERATE_INFOPLIST_FILE'] = 'NO'
    config.build_settings['CURRENT_PROJECT_VERSION'] = '17'
    config.build_settings['MARKETING_VERSION'] = '1.2.0'
  end
  
  # Embed into Runner (PlugIns)
  embed_phase = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed App Extensions' }
  if embed_phase.nil?
    embed_phase = runner_target.new_copy_files_build_phase('Embed App Extensions')
    embed_phase.dst_subfolder_spec = '13'
    embed_phase.dst_path = ''
  end
  embed_phase.add_file_reference(widget_target.product_reference, true)
  
  runner_target.add_dependency(widget_target)
  puts "Added SobrietyWidgets target and embedded in Runner"
else
  puts "SobrietyWidgets target already exists"
end

# 2. Add SobrietyWatch target
watch_target = project.targets.find { |t| t.name == 'SobrietyWatch' }
if watch_target.nil?
  watch_target = project.new_target(:watch2_app, 'SobrietyWatch', :watchos, '9.0', project.products_group, :swift)
  
  watch_group = project.main_group.find_subpath('SobrietyWatch', true)
  watch_group.set_source_tree('<group>')
  watch_group.set_path('SobrietyWatch')
  
  watch_swift = watch_group.new_file('SobrietyWatchApp.swift')
  session_swift = watch_group.new_file('WatchSessionManager.swift')
  watch_plist = watch_group.new_file('Info.plist')
  
  watch_target.source_build_phase.add_file_reference(watch_swift)
  watch_target.source_build_phase.add_file_reference(session_swift)
  
  watch_target.build_configurations.each do |config|
    config.build_settings['PRODUCT_NAME'] = 'SobrietyWatch'
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'com.sobrietycopilot.app.watchkitapp'
    config.build_settings['INFOPLIST_FILE'] = 'SobrietyWatch/Info.plist'
    config.build_settings['DEVELOPMENT_TEAM'] = team_id
    config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
    config.build_settings['SWIFT_VERSION'] = '5.0'
    config.build_settings['TARGETED_DEVICE_FAMILY'] = '4'
    config.build_settings['WATCHOS_DEPLOYMENT_TARGET'] = '9.0'
    config.build_settings['GENERATE_INFOPLIST_FILE'] = 'NO'
    config.build_settings['CURRENT_PROJECT_VERSION'] = '17'
    config.build_settings['MARKETING_VERSION'] = '1.2.0'
  end
  
  # Embed into Runner (Watch)
  watch_embed_phase = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed Watch Content' }
  if watch_embed_phase.nil?
    watch_embed_phase = runner_target.new_copy_files_build_phase('Embed Watch Content')
    watch_embed_phase.dst_subfolder_spec = '16'
    watch_embed_phase.dst_path = '$(CONTENTS_FOLDER_PATH)/Watch'
  end
  watch_embed_phase.add_file_reference(watch_target.product_reference, true)
  
  runner_target.add_dependency(watch_target)
  puts "Added SobrietyWatch target and embedded in Runner"
else
  puts "SobrietyWatch target already exists"
end

project.save
puts "Successfully saved project with embedded Widget & Watch targets"
