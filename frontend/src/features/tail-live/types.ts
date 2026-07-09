export interface ModelFeatureSnapshot {
  feature: string
  value: number | null
}

export interface ModelScore {
  model_version?: string | null
  model_score?: number | null
  hit_probability?: number | null
  expected_high_return?: number | null
  risk_probability?: number | null
  feature_snapshot?: ModelFeatureSnapshot[]
}

export interface Credibility {
  score: number
  grade: '高' | '中' | '低'
  rule_score?: number
  rule_grade?: '高' | '中' | '低'
  historical_hit_rate?: number | null
  historical_avg_return?: number | null
  sample_size?: number
  calibrated_probability?: number | null
  history_status?: string
  phase: string
  components: {
    signal_strength: number
    volume_quality: number
    return_quality: number
    phase_discount: number
  }
  confirmation_checks: string[]
  risks: string[]
  history: {
    status: string
    sample_count: number
    note: string
    close_win_rate?: number
    avg_close_return?: number
    max_win_rate?: number
    avg_max_return?: number
    avg_min_return?: number
  }
}

export interface SelectionRow {
  rank?: number
  raw_rank?: number | null
  final_candidate_rank?: number | null
  symbol: string
  trade_date: string
  strength: number
  last_price: number
  volume_ratio: number
  tail_return: number
  tail_high_return?: number
  pullback_from_high?: number
  close_position?: number
  reason: string
  status?: 'selected' | 'filtered'
  filter_reason?: string | null
  v2_score?: number
  v2_layer?: 'strong' | 'watchlist' | 'weak'
  v2_action?: 'trade_candidate' | 'observe_next_open' | 'no_trade'
  v2_explanation?: string
  v2_risks?: string[]
  v2_breakdown?: {
    tail_money: number
    price_action: number
    liquidity: number
    risk_control: number
  }
  credibility?: Credibility
  tradability?: {
    buyable: boolean
    reason?: string | null
    price?: number | null
    limit_up?: number | null
    limit_up_distance?: number | null
    execution_flag?: string | null
    score?: number | null
  }
  next_day_plan?: {
    entry_policy: string
    sell_policy?: string
    gap_stop_return: number | null
    intraday_stop_return: number | null
    take_profit_return: number | null
    rules: string[]
  }
  score_breakdown?: {
    strength: number
    volume_ratio: number
    tail_return: number
    pullback_penalty: number
    v2_total?: number | null
  }
  model?: ModelScore
}

export interface PrecheckRow {
  rank: number
  symbol: string
  data_status: 'has_intraday_data' | 'missing_intraday_data'
  latest_intraday_time: string | null
  stage: 'waiting_tail_window' | 'waiting_data'
  filter_reason: string
  explanation: string
}

export interface StrategyRules {
  universe: string
  tail_window: string
  bar_frequency: string
  preview_window_bars: number
  volume_ratio_threshold: number
  min_tail_return: number
  confirmations: number
  top_n: number
  min_strength: number | null
  min_market_breadth_above_ma20: number | null
  ranking: string
}

export interface TailLiveResult {
  mode?: 'precheck' | 'preview' | 'selection'
  trade_date: string
  scanned_count: number
  candidate_count: number
  confirmed_count: number
  selected_count: number
  preview_count?: number
  selections: SelectionRow[]
  preview_signals?: SelectionRow[]
  ranked_signals?: SelectionRow[]
  signal_layers?: {
    strong: number
    watchlist: number
    weak: number
  }
  watchlist_signals?: SelectionRow[]
  weak_signals?: SelectionRow[]
  precheck_rows?: PrecheckRow[]
  strategy_rules?: StrategyRules
  files: Record<string, string>
  market_breadth: { breadth: number; above_count: number; symbol_count: number } | null
  diagnostics?: {
    empty_reason: string | null
    empty_message: string | null
    scan_universe_preview: string[]
    has_intraday_data_count: number
    checked_intraday_count: number
    missing_intraday_symbols: string[]
    latest_intraday_time: string | null
    scan_as_of_time?: string | null
    scoreable_count: number
    unscoreable_count: number
    candidate_count: number
    confirmed_count: number
    selected_count: number
    blocked_by_market_breadth: boolean
    requested_scan_limit?: number
    resolved_scan_count?: number
    data_freshness?: {
      status: string
      latest_time: string | null
      target_time: string | null
      lag_minutes: number | null
      tradable: boolean
    }
    quote_status?: {
      status: string
      requested_symbols: number
      covered_symbols: number
      coverage_ratio: number
      error?: string
    }
    minute5_sync?: {
      trade_date?: string
      target_symbols?: number
      skipped?: number
      success?: number
      no_data?: number
      failed?: number
      inserted_rows?: number
      latest_datetime?: string | null
    }
    data_refresh_mode?: 'auto' | 'snapshot' | 'standard_minute5' | 'none'
    effective_data_refresh_mode?: 'snapshot' | 'standard_minute5' | 'none'
    strategy_mode?: 'rule' | 'model' | 'hybrid'
    quote_snapshot_sync?: {
      target_symbols?: number
      inserted_rows?: number
      skipped?: number
      failed?: number
      latest_snapshot_at?: string | null
      latest_bucket?: string | null
    }
    effective_strategy_mode?: 'rule' | 'model' | 'hybrid'
    model_status?: string
    model_scored_symbols?: number
    model_score_rank_limit?: number
    model_selection_applied?: boolean
    model_selection_mode?: 'rule' | 'model' | 'hybrid'
  }
  stage_timings?: Record<string, number>
  persistence?: {
    signals?: {
      signal_count?: number
      selected_count?: number
    }
  }
}
