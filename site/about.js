/* About Ice Sheet: what's here, how the numbers are made, where the data comes from, how AI is used,
   responsible gambling and privacy. #about/<section> scrolls to a section. Plain copy, no data needed
   beyond a few live counts from the loaded files. */
"use strict";

const ABOUT_TOC = [["tabs", "What's on each page"], ["methods", "How the numbers work"], ["glossary", "Glossary"], ["data", "Data and credits"],
  ["ai", "How we use AI"], ["gambling", "Responsible gambling"], ["privacy", "Privacy"]];

const SITE_GLOSSARY = [
  ["Expected goals (xG)", "The chance an unblocked shot becomes a goal, based on where it was taken, the shot type, whether it was a rebound or off the rush, and what happened just before. A shot from the slot might be worth 0.20 xG; a point shot through traffic 0.03. Add up a team's or player's shots and you get how many goals their chances usually produce."],
  ["Expected goal share (xG share)", "A team's share of all the expected goals in its games. 50% is an even split; 55% means it's creating more and better chances than it allows. Over a season it predicts future results better than goals or record do."],
  ["Per 60", "A rate per 60 minutes of ice time, so players with different roles can be compared fairly."],
  ["5v5, power play, penalty kill", "Five on five is regular even-strength play and most of every game. On the power play a team has an extra skater because of a penalty; the other team is on the penalty kill."],
  ["Finishing (goals minus xG)", "Goals scored minus the goals the chances usually produce. A big positive number means the puck is going in more than usual, which rarely lasts; a negative one often means goals are coming."],
  ["Goals saved above expected (GSAx)", "Expected goals faced minus goals allowed. Positive means a goalie stopped more than an average goalie would have on the same shots."],
  ["High-danger", "Shots worth 15% or more to go in, mostly from the slot and right in front. Low danger is under 6%."],
  ["Team better with him", "The team's share of five-on-five expected goals with the player on the ice, minus its share without him. +5 means the team gets five points more of the chances when he plays."],
  ["On-ice xG ±", "Expected goals for minus expected goals against while a player was on the ice in one game."],
  ["Deserved to win", "How often a team would win if every shot in the game were replayed with its chance of going in. Under 35% for the actual winner means it got away with one."],
  ["Fair odds", "The American odds that match our probability exactly, with no bookmaker margin. A 25% chance is +300."],
  ["Expected return", "What a bet returns on average if our probability is right: chance times the payout, minus your stake. Positive means the price is better than our number says it should be. It's an estimate, not a promise."],
  ["Sleeper", "One of our own under-the-radar picks for a game: a depth forward whose recent shots have been dangerous against a defense that gives chances up, or a player whose chance of a point is clearly above his season pace because his role or matchup has changed. Never just \"he's due\"."],
  ["Back-to-back", "The second of two games on consecutive days. Last season, teams in that spot got 47.4% of the expected goals."],
  ["GAR, WAR and xWAR", "Evolving-Hockey's estimates of a player's total value: goals above replacement, wins above replacement (about six goals make a win), and the same built from expected goals rather than actual goals."],
  ["RAPM", "Regularized adjusted plus-minus: Evolving-Hockey's estimate of a player's impact on chances for and against after adjusting for teammates, opponents, score and zone starts."],
  ["Royal-road pass", "A pass across the middle of the offensive zone right before a shot. It makes the goalie move side to side, and those shots go in far more often."],
  ["Carry-in, controlled exit", "Entering the offensive zone with the puck instead of dumping it in, and leaving your own zone with possession instead of clearing it. Carry-ins lead to chances about three times as often as dump-ins."],
  ["Own-end starts", "The share of a player's five-on-five faceoffs that happen in his own zone. Coaches give those to players they trust defensively."],
  ["Percentile", "Where a player ranks among players at his position. 90th means better than 90% of them. We only rank players with enough minutes to mean something."],
];

function renderAbout(view) {
  const M = D.model || {}, sec = (id, title, body) => `<section class="zone about-sec" id="about-${id}"><h2>${title}</h2>${body}</section>`;
  const nGames = (M.games || 1241).toLocaleString(), nPG = (M.player_games || 44000).toLocaleString();
  view.innerHTML = `
    <section class="zone about-top">
      <h1>About Ice Sheet</h1>
      <p class="lede">Ice Sheet explains every NHL game with the numbers behind it. Records and box scores tell you what happened; we try to show why, and what's likely to happen next. Who's creating the chances, who's riding the bounces, which goalie is stealing games, how coaches use their players, and who's most likely to score tonight.</p>
      <p class="lede">We update every morning after the last game ends, refresh again in the afternoon for lineup and goalie news, and follow live scores every night.</p>
      <nav class="about-toc" aria-label="On this page">${ABOUT_TOC.map(([k, l]) => `<a class="chip" href="#about/${k}">${l}</a>`).join("")}</nav>
    </section>
    ${sec("tabs", "What's on each page", `<dl class="about-dl">
      <dt><a href="#tonight">Tonight</a></dt><dd>Every game on today's schedule: how many goals we expect each team to score, the starting goalies (switch them and everything updates), the sportsbook line next to ours, our sleepers, the storylines, and every skater's chance to score, reach 1, 2 or 3+ points, or put 2 or 3+ shots on goal. Each game has a full preview and a live page once it starts.</dd>
      <dt><a href="#games">Games</a></dt><dd>Every finished game: every shot on a rink map, how the chances piled up, who deserved to win, player-by-player numbers, a replay of every goal rebuilt from the NHL's play-by-play, and the official highlights.</dd>
      <dt><a href="#pulse">Pulse</a></dt><dd>Who's hot, who's cold and whether it's real, young players breaking out, rookies, players due for more goals or due to cool off, goalie form and milestones in reach.</dd>
      <dt><a href="#news">News</a></dt><dd>The day's headlines grouped by story, with a short take on what our numbers say; every trade, signing and call-up; our own features; and the latest from hockey's best podcasts and video channels.</dd>
      <dt><a href="#league">League</a></dt><dd>Every team placed by the chances it creates and allows, the standings with luck shown, and every goalie ranked by goals saved.</dd>
      <dt><a href="#teams">Teams</a></dt><dd>One team's season: record and the chances behind it, shot map, forward lines, defense pairs and special-teams units, who plays when, goalies and every game.</dd>
      <dt><a href="#players">Players</a></dt><dd>Search any skater or goalie. Player pages have a shot map, game log, what he's worth, how he defends, how he plays (from hand-tracked data) and his highlights. Follow players to keep them one tap away.</dd>
      <dt><a href="#model">Track record</a></dt><dd>How accurate our numbers have been, on last season and on every night this season.</dd>
    </dl>`)}
    ${sec("methods", "How the numbers work", `
      <h3>Expected goals</h3>
      <p>Almost everything here starts with expected goals: the chance each unblocked shot had of going in, based on where it came from, the type of shot, whether it was a rebound or off the rush, and what happened in the seconds before. Goals are rare and noisy; chances happen dozens of times a game, so they show who's playing well much sooner. For finished games we use <a href="https://moneypuck.com">MoneyPuck.com</a>'s shot model. Our own model fills the gaps and rates shots live during games.</p>
      <h3>Tonight's probabilities</h3>
      <p>For every skater in tonight's games we estimate how many goals and points he should produce, then turn that into probabilities. The estimate combines his shooting and playmaking rates (this season blended with last season, so two hot weeks don't swing everything), his expected ice time and power-play role, how well his linemates finish, the opponent's defense and goalie, rest, and, for players with hand-tracked passing data, how often he sets up dangerous chances. Starting goalies come from ESPN's probable starters once they're posted. Every probability assumes the player dresses.</p>
      <p>Game totals and win chances come from the same team ratings. In testing, our totals didn't beat a simple league-average guess, so we show them next to the sportsbook line as context, not as a prediction.</p>
      <h3>How we test it</h3>
      <p>We replayed the whole 2025-26 season (${nGames} games, ${nPG} player-games), predicting each night using only the games before it. Our goal and point probabilities were well calibrated and beat a simple baseline every month. This season, every number on the Tonight page is saved at puck drop and graded the next morning on the <a href="#model">Track record</a> page, including how often we got the lineups and starting goalies right.</p>
      <h3>Sleepers</h3>
      <p>Each game can get up to two sleepers: our own under-the-radar picks. A depth scorer is a third- or fourth-line forward whose recent shots have been genuinely dangerous (his expected goals over the last ten games rank in the top 30% of depth forwards, with several high-danger looks) and who faces a defense or goalie that gives chances up. An underrated point pick is a player whose chance of a point tonight is clearly above what his season scoring suggests, because his ice time, power-play role or line has changed, his line drives chances, or the matchup is soft. We never pick a player just because his goals have lagged his chances. They're long shots by design, and every one is graded on the Track record page.</p>
      <h3>Injuries and who steps in</h3>
      <p>When a regular is out, we look at the shift charts: if his team has already played without him, we report who took his spot on his line or power-play unit and whose minutes jumped. If it hasn't, we name the likeliest candidates from how the coach has used his players. Tonight's numbers lean heavily on each player's last three games, so a promotion starts to show up in his projection after one game. We tested moving minutes around before that, and it didn't make the projections better.</p>
      <h3>Hot, cold, and whether it's real</h3>
      <p>On the Pulse, a player is hot or cold when his points over the last ten games are well above or below what we'd expect at his ice time. Then we check the chances: if his expected goals are up too, the streak is earned; if they aren't, it's bounces and likely to cool. Thresholds are strict early in the season, and every note says how many games it's based on.</p>
      <h3>Defense, goalies and deployment</h3>
      <p>Defensive numbers compare the chances a team allows with a player on the ice to the chances it allows while he's on the bench, which takes out most of the team's overall quality. Goalie save rates are split by shot danger, because high-danger saves are where goalies separate. Lines, pairs and special-teams units come from the NHL's shift charts: every stretch where the same skaters were on the ice together.</p>
      <h3>Small samples</h3>
      <p>Hockey is noisy. A few games can make anyone look great or lost. We say when a number rests on a small sample, and early in the season our projections lean on last season more than this one.</p>`)}
    ${sec("glossary", "Glossary", `<dl class="about-dl gloss">${SITE_GLOSSARY.map(([t, d]) => `<dt>${t}</dt><dd>${d}</dd>`).join("")}</dl>`)}
    ${sec("data", "Data and credits", `
      <ul class="about-list">
        <li><b>The NHL</b>: schedules, play-by-play, shift charts, box scores and NHL EDGE player tracking (skating speed, shot speed, shot locations). Player headshots and highlight clips are the NHL's own: headshots load from the NHL's servers, clips open on NHL.com, and highlight videos play through the NHL's YouTube channel.</li>
        <li><b><a href="https://moneypuck.com">MoneyPuck.com</a></b>: shot-by-shot expected goals for every finished game.</li>
        <li><b><a href="https://www.allthreezones.com">All Three Zones</a></b> (Corey Sznajder): hand-tracked passing, zone entries and zone exits for about a third of each season's games, shown with permission.</li>
        <li><b><a href="https://evolving-hockey.com">Evolving-Hockey</a></b>: GAR, WAR, xWAR and RAPM player value models, shown with permission.</li>
        <li><b>ESPN</b>: live scores, probable starting goalies, injury reports, transactions and headlines.</li>
        <li><b>Sportsbook lines</b>: DraftKings moneylines and totals as published by the NHL, for comparison only.</li>
        <li><b>News, podcasts and video</b>: we show headlines and short teasers and link to the publisher; podcasts play from each show's public feed; videos play through YouTube's own player. Some links need a subscription to that publisher.</li>
      </ul>
      <p class="note">Ice Sheet is an independent site. We're not affiliated with or endorsed by the NHL, the NHLPA, any team, ESPN or any sportsbook. Team names and abbreviations belong to their owners.</p>`)}
    ${sec("ai", "How we use AI", `
      <p>Some of the writing on Ice Sheet is generated by AI: game recaps and previews, the short takes on news stories, notes on trades and staff moves, and the column and deep dives on the Features tab. It's written by Claude, an AI model made by Anthropic, from Ice Sheet's own data (and, for news takes, the headlines and teasers of the linked reports). It contains no outside reporting, interviews or quotes, and every AI-written piece is labeled.</p>
      <p>Everything else, including every number, chart, storyline and note on game, team and player pages, is produced directly from the data by code. AI writing can still get something wrong. If a sentence and a number disagree, trust the number.</p>`)}
    ${sec("gambling", "Responsible gambling", `
      <p>Our probabilities are estimates published for information and entertainment. They aren't betting advice, and nothing here guarantees a result. Ice Sheet doesn't take bets, sell picks or get paid by sportsbooks.</p>
      <p>If you bet, do it only where it's legal, only if you're of legal age where you live (21 in most US states), and only with money you can afford to lose. Set a budget before you start and don't chase losses.</p>
      <p><b>Gambling problem? Call 1-800-GAMBLER</b> (US, free and confidential, 24/7). In Canada, contact your provincial problem gambling helpline.</p>`)}
    ${sec("privacy", "Privacy", `
      <p>There are no accounts and no ads. Your team, the players you follow, odds you type, goalie picks and your light or dark setting are saved in your own browser and never sent to us. Clearing your browser data resets them.</p>
      <p>Some things load from other services as you browse: fonts from Google Fonts, headshots from the NHL, live scores and injuries from ESPN, and videos from YouTube (only when you press play). Those services see the request like any other website visit.</p>`)}`;
}
