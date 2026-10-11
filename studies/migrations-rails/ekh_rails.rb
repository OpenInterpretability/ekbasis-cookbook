# Eval harness, inside the project container: `bin/rails runner /tmp/ekh_rails.rb`. EKH_ACTION plan | apply.
require "json"
action = ENV.fetch("EKH_ACTION")
ctx = ActiveRecord::Base.connection_pool.migration_context
out = nil
if action == "plan"
  prev = nil
  out = ctx.migrations.sort_by(&:version).map do |m|
    rec = { "node" => [m.version.to_s], "path" => m.filename.sub("#{Rails.root}/", ""),
            "atomic" => !m.disable_ddl_transaction, "replaces" => false, "down" => prev ? [prev] : [] }
    prev = m.version.to_s
    rec
  end
elsif action == "apply"
  done, failed, err = [], nil, nil
  JSON.parse(ENV.fetch("EKH_NODES")).each do |n|
    begin
      ctx.run(:up, n[0].to_i)
      done << n
    rescue StandardError => e
      failed, err = n, "#{e.class}: #{e.message}"[0, 600]
      break
    end
  end
  out = { "done" => done, "failed" => failed, "error" => err }
end
puts "EKBASIS-JSON:" + JSON.generate(out)
