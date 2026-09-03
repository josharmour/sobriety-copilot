require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

# Remove watch embed phase and target dependency if watchOS SDK is not installed locally
watch_target = project.targets.find { |t| t.name == 'SobrietyWatch' }
if watch_target
  runner_target.dependencies.delete_if { |dep| dep.target == watch_target }
  watch_embed = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed Watch Content' }
  runner_target.build_phases.delete(watch_embed) if watch_embed
  puts "Unlinked SobrietyWatch from Runner embed phases (can be built standalone when watchOS SDK is installed)"
end

project.save
puts "Saved Xcode project with SobrietyWidgets target embedded in Runner"
