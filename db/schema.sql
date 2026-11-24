CREATE TABLE backtest_runs (
	id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	config JSON, 
	results JSON, 
	PRIMARY KEY (id)
);

CREATE TABLE ingest_fixtures (
	sportmonks_fixture_id INTEGER NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	attempts INTEGER NOT NULL, 
	consecutive_failures INTEGER NOT NULL, 
	last_error TEXT, 
	last_status VARCHAR(40), 
	blocked BOOLEAN NOT NULL, 
	blocked_reason VARCHAR(80), 
	last_attempt_utc DATETIME, 
	last_attempt_ist DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (sportmonks_fixture_id)
);

CREATE TABLE mapping_experiments (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	hypothesis TEXT, 
	params JSON, 
	result JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE players (
	id INTEGER NOT NULL, 
	sportmonks_id INTEGER, 
	name VARCHAR(160) NOT NULL, 
	role VARCHAR(40), 
	PRIMARY KEY (id)
);

CREATE TABLE rules (
	id INTEGER NOT NULL, 
	rule_id VARCHAR(60) NOT NULL, 
	condition TEXT, 
	outcome TEXT, 
	authority VARCHAR(40), 
	status VARCHAR(40), 
	notes TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE teams (
	id INTEGER NOT NULL, 
	sportmonks_id INTEGER, 
	name VARCHAR(120) NOT NULL, 
	code VARCHAR(20), 
	PRIMARY KEY (id)
);

CREATE TABLE venues (
	id INTEGER NOT NULL, 
	sportmonks_id INTEGER, 
	name VARCHAR(160) NOT NULL, 
	city VARCHAR(120), 
	country VARCHAR(120), 
	lat FLOAT, 
	lon FLOAT, 
	timezone VARCHAR(60), 
	coords_source VARCHAR(20), 
	PRIMARY KEY (id)
);

CREATE TABLE matches (
	id INTEGER NOT NULL, 
	sportmonks_fixture_id INTEGER, 
	format VARCHAR(20), 
	league VARCHAR(120), 
	season VARCHAR(40), 
	localteam_id INTEGER, 
	visitorteam_id INTEGER, 
	venue_id INTEGER, 
	starting_at_utc DATETIME, 
	starting_at_ist DATETIME, 
	first_ball_utc DATETIME, 
	first_ball_ist DATETIME, 
	lat FLOAT, 
	lon FLOAT, 
	toss_won_team_id INTEGER, 
	toss_elected VARCHAR(20), 
	status VARCHAR(40), 
	winner_team_id INTEGER, 
	result_note TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(localteam_id) REFERENCES teams (id), 
	FOREIGN KEY(visitorteam_id) REFERENCES teams (id), 
	FOREIGN KEY(venue_id) REFERENCES venues (id), 
	FOREIGN KEY(toss_won_team_id) REFERENCES teams (id), 
	FOREIGN KEY(winner_team_id) REFERENCES teams (id)
);

CREATE TABLE rule_confidence (
	id INTEGER NOT NULL, 
	rule_id VARCHAR(60) NOT NULL, 
	matches_tested INTEGER, 
	success_rate FLOAT, 
	confidence VARCHAR(40), 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(rule_id) REFERENCES rules (rule_id)
);

CREATE TABLE astro_charts (
	id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	datetime_utc DATETIME NOT NULL, 
	datetime_ist DATETIME, 
	lat FLOAT NOT NULL, 
	lon FLOAT NOT NULL, 
	ayanamsa VARCHAR(40) NOT NULL, 
	ayanamsa_value FLOAT, 
	julian_day FLOAT, 
	duration_hours FLOAT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches (id)
);

CREATE TABLE innings (
	id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	innings_number INTEGER NOT NULL, 
	batting_team_id INTEGER, 
	bowling_team_id INTEGER, 
	start_utc DATETIME, 
	end_utc DATETIME, 
	start_ist DATETIME, 
	end_ist DATETIME, 
	total_runs INTEGER, 
	wickets INTEGER, 
	overs FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_innings_match_number UNIQUE (match_id, innings_number), 
	FOREIGN KEY(match_id) REFERENCES matches (id), 
	FOREIGN KEY(batting_team_id) REFERENCES teams (id), 
	FOREIGN KEY(bowling_team_id) REFERENCES teams (id)
);

CREATE TABLE learning_reports (
	id INTEGER NOT NULL, 
	match_id INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	report TEXT, 
	suggested_updates JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches (id)
);

CREATE TABLE predictions (
	id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	made_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	phase VARCHAR(40), 
	target VARCHAR(60), 
	predicted_value TEXT, 
	confidence FLOAT, 
	reasoning TEXT, 
	actual_value TEXT, 
	correct BOOLEAN, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches (id)
);

CREATE TABLE astro_cusps (
	id INTEGER NOT NULL, 
	chart_id INTEGER NOT NULL, 
	cusp_no INTEGER NOT NULL, 
	longitude FLOAT, 
	sign VARCHAR(20), 
	sign_lord VARCHAR(10), 
	nl VARCHAR(10), 
	sl VARCHAR(10), 
	ssl VARCHAR(10), 
	sssl VARCHAR(10), 
	PRIMARY KEY (id), 
	FOREIGN KEY(chart_id) REFERENCES astro_charts (id)
);

CREATE TABLE astro_planets (
	id INTEGER NOT NULL, 
	chart_id INTEGER NOT NULL, 
	planet VARCHAR(10) NOT NULL, 
	longitude FLOAT, 
	sign VARCHAR(20), 
	sign_lord VARCHAR(10), 
	nl VARCHAR(10), 
	sl VARCHAR(10), 
	ssl VARCHAR(10), 
	sssl VARCHAR(10), 
	is_retrograde BOOLEAN NOT NULL, 
	speed FLOAT, 
	significators JSON, 
	significators_display VARCHAR(500), 
	PRIMARY KEY (id), 
	FOREIGN KEY(chart_id) REFERENCES astro_charts (id)
);

CREATE TABLE astro_timeline_periods (
	id INTEGER NOT NULL, 
	chart_id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	body VARCHAR(20) NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	start_utc DATETIME NOT NULL, 
	end_utc DATETIME NOT NULL, 
	start_ist DATETIME, 
	end_ist DATETIME, 
	nl VARCHAR(10), 
	sl VARCHAR(10), 
	ssl VARCHAR(10), 
	sssl VARCHAR(10), 
	longitude_start FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(chart_id) REFERENCES astro_charts (id), 
	FOREIGN KEY(match_id) REFERENCES matches (id)
);

CREATE TABLE ball_events (
	id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	innings_id INTEGER, 
	over INTEGER, 
	ball INTEGER, 
	ball_seq INTEGER, 
	batsman_id INTEGER, 
	bowler_id INTEGER, 
	runs INTEGER, 
	extras INTEGER, 
	is_wicket BOOLEAN NOT NULL, 
	is_four BOOLEAN NOT NULL, 
	is_six BOOLEAN NOT NULL, 
	score_after INTEGER, 
	wickets_after INTEGER, 
	commentary TEXT, 
	event_utc DATETIME, 
	event_ist DATETIME, 
	time_source VARCHAR(20) NOT NULL, 
	event_utc_treated DATETIME, 
	event_ist_treated DATETIME, 
	event_utc_corrected DATETIME, 
	event_ist_corrected DATETIME, 
	time_correction_sec FLOAT, 
	timestamp_in_burst BOOLEAN NOT NULL, 
	sportmonks_ball_id INTEGER, 
	ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ball_match_innings_seq UNIQUE (match_id, innings_id, ball_seq), 
	FOREIGN KEY(match_id) REFERENCES matches (id), 
	FOREIGN KEY(innings_id) REFERENCES innings (id), 
	FOREIGN KEY(batsman_id) REFERENCES players (id), 
	FOREIGN KEY(bowler_id) REFERENCES players (id)
);

CREATE TABLE prediction_evidence (
	id INTEGER NOT NULL, 
	prediction_id INTEGER NOT NULL, 
	rule_id VARCHAR(60), 
	evidence JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(prediction_id) REFERENCES predictions (id)
);

CREATE TABLE ball_astro_state (
	id INTEGER NOT NULL, 
	ball_id INTEGER NOT NULL, 
	asc_nl VARCHAR(10), 
	asc_sl VARCHAR(10), 
	asc_ssl VARCHAR(10), 
	asc_sssl VARCHAR(10), 
	moon_nl VARCHAR(10), 
	moon_sl VARCHAR(10), 
	moon_ssl VARCHAR(10), 
	moon_sssl VARCHAR(10), 
	asc_period_id INTEGER, 
	moon_period_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ball_id) REFERENCES ball_events (id), 
	FOREIGN KEY(asc_period_id) REFERENCES astro_timeline_periods (id), 
	FOREIGN KEY(moon_period_id) REFERENCES astro_timeline_periods (id)
);

CREATE TABLE odds_snapshots (
	id INTEGER NOT NULL, 
	match_id INTEGER NOT NULL, 
	captured_utc DATETIME NOT NULL, 
	captured_ist DATETIME, 
	updated_at_source DATETIME, 
	market VARCHAR(80), 
	bookmaker VARCHAR(80), 
	selection VARCHAR(120), 
	odd_value FLOAT, 
	is_inplay BOOLEAN NOT NULL, 
	raw JSON, 
	asc_ssl VARCHAR(10), 
	asc_sssl VARCHAR(10), 
	moon_ssl VARCHAR(10), 
	moon_sssl VARCHAR(10), 
	asc_period_id INTEGER, 
	moon_period_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_odds_change UNIQUE (match_id, market, bookmaker, selection, updated_at_source), 
	FOREIGN KEY(match_id) REFERENCES matches (id), 
	FOREIGN KEY(asc_period_id) REFERENCES astro_timeline_periods (id), 
	FOREIGN KEY(moon_period_id) REFERENCES astro_timeline_periods (id)
);
