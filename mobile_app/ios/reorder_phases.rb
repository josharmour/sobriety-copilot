require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

# Get existing phases by name
check_pods = runner_target.build_phases.find { |p| p.display_name.include?('Check Pods') }
flutter_run = runner_target.build_phases.find { |p| p.display_name == 'Run Script' }
sources = runner_target.source_build_phase
frameworks = runner_target.frameworks_build_phase
resources = runner_target.resources_build_phase
embed_ext = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed App Extensions' }
embed_fw = runner_target.copy_files_build_phases.find { |p| p.name == 'Embed Frameworks' }
thin_binary = runner_target.build_phases.find { |p| p.display_name == 'Thin Binary' }
cp_embed_pods = runner_target.build_phases.find { |p| p.display_name.include?('Embed Pods') }
cp_copy_pods = runner_target.build_phases.find { |p| p.display_name.include?('Copy Pods') }

ordered_phases = [
  check_pods,
  flutter_run,
  sources,
  frameworks,
  resources,
  embed_ext,
  embed_fw,
  cp_embed_pods,
  cp_copy_pods,
  thin_binary
].compact

runner_target.build_phases.clear
ordered_phases.each { |phase| runner_target.build_phases << phase }

project.save
puts "Set canonical build phase order in Runner:"
runner_target.build_phases.each_with_index { |p, i| puts "  #{i + 1}. #{p.display_name}" }
