import { getDbConnection, getDiscoveryStats } from '../src/utils/db.js';
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

const GOAL_PERCENT = 80;
const TOTAL_SCHOOLS = 2232;
const TARGET_PROCESSED = Math.ceil(TOTAL_SCHOOLS * (GOAL_PERCENT / 100));
const POLL_INTERVAL_MS = 15000;
const REPORT_STEP = 50;
const WATCHDOG_TIMEOUT_MS = 10 * 60 * 1000;
const LOG_MAX_WAIT_MS = 5 * 60 * 1000;

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function parseErrorsFromLog() {
  const logPath = './logs/controller.log';
  if (!fs.existsSync(logPath)) {
    return { counts: {}, sampleErrors: [] };
  }

  try {
    const fileContent = fs.readFileSync(logPath, 'utf-8');
    const lines = fileContent.split('\n');
    const recentLines = lines.slice(-200);

    const errorCounts = {
      timeout: 0,
      rateLimit429: 0,
      feeSelectMissing: 0,
      other: 0
    };
    const sampleErrors = [];

    recentLines.forEach(line => {
      if (line.includes('[ERROR]') || line.includes('✗ Failed') || line.includes('⚠️ Attempt')) {
        if (line.includes('Timeout') || line.includes('timeout')) {
          errorCounts.timeout++;
        } else if (line.includes('429') || line.includes('Rate limit')) {
          errorCounts.rateLimit429++;
        } else {
          errorCounts.other++;
        }
        if (sampleErrors.length < 5 && line.trim()) {
          sampleErrors.push(line.trim());
        }
      } else if (line.includes('Fee select not in DOM')) {
        errorCounts.feeSelectMissing++;
      }
    });

    return { counts: errorCounts, sampleErrors };
  } catch (err) {
    console.error(`Error parsing controller log: ${err.message}`);
    return { counts: {}, sampleErrors: [] };
  }
}

async function runMonitor() {
  console.log(`====================================================`);
  console.log(`Starting Autopilot Scraper Monitor`);
  console.log(`Target: At least ${TARGET_PROCESSED} processed schools (${GOAL_PERCENT}% of ${TOTAL_SCHOOLS})`);
  console.log(`====================================================\n`);

  let lastProcessedCount = 0;
  let lastProgressTime = Date.now();
  let lastLogTime = Date.now();
  let firstCheck = true;

  try {
    const db = await getDbConnection();
    const stats = await getDiscoveryStats(db);
    lastProcessedCount = stats.processed;
    await db.close();
  } catch (e) {
    console.error(`Failed to get initial stats: ${e.message}`);
  }

  while (true) {
    let db;
    let stats = { processed: 0, pending: 0, failed: 0 };
    
    try {
      db = await getDbConnection();
      stats = await getDiscoveryStats(db);
      await db.close();
    } catch (dbErr) {
      console.error(`[Monitor Error] Database connection failed: ${dbErr.message}`);
      await sleep(POLL_INTERVAL_MS);
      continue;
    }

    const currentPercent = ((stats.processed / TOTAL_SCHOOLS) * 100).toFixed(2);
    
    if (stats.processed > lastProcessedCount) {
      lastProgressTime = Date.now();
    }

    const diff = stats.processed - lastProcessedCount;
    const timeSinceLastLog = Date.now() - lastLogTime;
    const timeSinceLastProgress = Date.now() - lastProgressTime;

    if (diff >= REPORT_STEP || timeSinceLastLog >= LOG_MAX_WAIT_MS || firstCheck) {
      firstCheck = false;
      lastLogTime = Date.now();
      lastProcessedCount = stats.processed;

      const errorsInfo = parseErrorsFromLog();

      console.log(`\n------------------ PROGRESS REPORT ------------------`);
      console.log(`Time: ${new Date().toLocaleString()}`);
      console.log(`Progress: ${stats.processed}/${TOTAL_SCHOOLS} schools processed (${currentPercent}%)`);
      console.log(`Pending: ${stats.pending} | Failed: ${stats.failed}`);
      console.log(`Change since last report: +${diff} schools processed`);
      
      console.log(`\n[Recent Error Metrics (last 200 log lines)]`);
      console.log(` - Timeout errors (20s page.goto): ${errorsInfo.counts.timeout || 0}`);
      console.log(` - HTTP 429 Rate limits: ${errorsInfo.counts.rateLimit429 || 0}`);
      console.log(` - Warning - Fee details missing in DOM: ${errorsInfo.counts.feeSelectMissing || 0}`);
      console.log(` - Other errors: ${errorsInfo.counts.other || 0}`);

      if (errorsInfo.sampleErrors.length > 0) {
        console.log(`\n[Sample Recent Log/Error Lines]`);
        errorsInfo.sampleErrors.forEach(err => console.log(`  > ${err}`));
      }
      console.log(`-----------------------------------------------------\n`);
      
      const reportMarkdown = `# Scraper Progress & Error Report
Last updated: ${new Date().toISOString()}

## Completion Stats
- **Processed**: ${stats.processed} / ${TOTAL_SCHOOLS} (${currentPercent}%)
- **Pending**: ${stats.pending}
- **Failed**: ${stats.failed}
- **Goal**: ${TARGET_PROCESSED} (80%)

## Recent Errors in last 200 lines
- Timeout (20s): ${errorsInfo.counts.timeout || 0}
- Rate limits (429): ${errorsInfo.counts.rateLimit429 || 0}
- Fee select not found: ${errorsInfo.counts.feeSelectMissing || 0}
- Other: ${errorsInfo.counts.other || 0}

## Sample Errors
${errorsInfo.sampleErrors.map(err => `- \`${err}\``).join('\n')}
`;
      fs.writeFileSync('./logs/progress_report.md', reportMarkdown, 'utf-8');
    }

    if (stats.processed >= TARGET_PROCESSED) {
      console.log(`\n====================================================`);
      console.log(`🎉 SUCCESS: Goal reached! Processed ${stats.processed} schools (>= ${TARGET_PROCESSED})`);
      console.log(`====================================================\n`);
      
      console.log('Running final export to generate "final_schools_data.json"...');
      try {
        execSync('node src/main.js export', { stdio: 'inherit' });
        console.log('✓ Export completed successfully.');
      } catch (err) {
        console.error(`Export failed: ${err.message}`);
      }
      break;
    }

    if (timeSinceLastProgress >= WATCHDOG_TIMEOUT_MS && stats.pending > 0) {
      console.log(`\n⚠️ WATCHDOG WARNING: No progress for ${Math.round(timeSinceLastProgress / 60000)} minutes.`);
      console.log('The scraper process might be hung. Attempting restart...');
      
      try {
        console.log('Killing active scraper child process via pkill...');
        execSync('pkill -f "node src/main.js extract"', { stdio: 'inherit' });
        console.log('✓ Sent kill signal to scraper.');
        lastProgressTime = Date.now();
      } catch (killErr) {
        console.error(`Failed to kill scraper: ${killErr.message}`);
      }
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

runMonitor().catch(err => {
  console.error('Fatal monitor error:', err);
});
