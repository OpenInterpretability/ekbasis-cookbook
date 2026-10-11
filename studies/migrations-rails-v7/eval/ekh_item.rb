# Eval harness (v7, one Rails boot per sampled migration), inside the project container: `bin/rails runner
# /tmp/ekh_item.rb`. 1) the PRODUCT's renderer (/tmp/ekbasis_rails.rb, loaded as is) on the render copy; 2) the label
# run of the migration on the seeded copy; 3) the progress database: this migration, then the ones before the next
# sampled migration. Each step uses its own connection (EKH_RENDER_URL, EKH_LABEL_URL, EKH_PROG_URL).
require "json"
require "stringio"
out = {}
v = ENV.fetch("EKH_NODE").to_i
ActiveRecord::Base.establish_connection(ENV.fetch("EKH_RENDER_URL"))
buf, old = StringIO.new, $stdout
$stdout = buf
begin
  load "/tmp/ekbasis_rails.rb"
rescue StandardError, ScriptError => e
  out["render_crash"] = "#{e.class}: #{e.message}"[0, 300]
ensure
  $stdout = old
end
ActiveSupport::Notifications.unsubscribe("sql.active_record")
line = buf.string.lines.find { |l| l.start_with?("EKBASIS-JSON:") }
out["render"] = line ? JSON.parse(line.sub("EKBASIS-JSON:", "")) : nil

def run_up(url, versions)
  ActiveRecord::Base.establish_connection(url)
  ActiveRecord::Base.connection.schema_cache.clear!
  ActiveRecord::Base.descendants.each { |k| k.reset_column_information rescue nil }
  ctx = ActiveRecord::Base.connection_pool.migration_context
  done = []
  versions.each do |x|
    begin
      ctx.run(:up, x.to_i)
      done << x
    rescue StandardError => e
      return { "done" => done, "failed" => x, "error" => "#{e.class}: #{e.message}"[0, 600] }
    end
  end
  { "done" => done, "failed" => nil, "error" => nil }
end

out["label"] = run_up(ENV.fetch("EKH_LABEL_URL"), [v])
out["progress"] = run_up(ENV.fetch("EKH_PROG_URL"), [v] + JSON.parse(ENV.fetch("EKH_PENDING", "[]")))
puts "EKBASIS-JSON:" + JSON.generate(out)
