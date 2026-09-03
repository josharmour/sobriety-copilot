require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

# Remove Fix Native Framework Plists phase to prevent dependency cycles
plist_script_phase = runner_target.shell_script_build_phases.find { |p| p.name == 'Fix Native Framework Plists' }
runner_target.build_phases.delete(plist_script_phase) if plist_script_phase

# Ensure Embed App Extensions is at the very end of build phases
embed_phase = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed App Extensions' }
if embed_phase
  runner_target.build_phases.delete(embed_phase)
  runner_target.build_phases << embed_phase
end

project.save
puts "Successfully re-ordered build phases in Runner"
