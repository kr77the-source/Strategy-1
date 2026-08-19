# =============================================================================
# TAB 3: BACKTEST & MASTER DATABASE (UPDATED WITH SUMMARY CARDS)
# =============================================================================
with tab3:
    st.markdown("### 📊 Dual Backtest Engine & Database Logs")
    
    if st.button("▶️ Run 60-Day Backtest", type="primary"):
        with st.spinner("Calculating 60-Day Historical Data via yfinance..."):
            norm_bt, rev_bt = run_60d_backtest(
                SELECTED_STOCKS, FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, 
                ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, 
                TIMEFRAME_MINS, SLIPPAGE_BPS
            )
            st.session_state.norm_bt = norm_bt
            st.session_state.rev_bt = rev_bt

    norm_bt = st.session_state.get("norm_bt")
    rev_bt = st.session_state.get("rev_bt")

    # --- NORMAL STRATEGY BACKTEST RESULTS ---
    if norm_bt is not None and not norm_bt.empty:
        st.markdown("#### 🟢 Normal Strategy Backtest Summary")
        
        t_trades = len(norm_bt)
        t_gross = norm_bt["GrossPnL"].sum()
        t_charges = norm_bt["Charges"].sum()
        t_net = round(t_gross - t_charges, 2)
        net_class = "metric-val-green" if t_net >= 0 else "metric-val-red"

        # Summary Card Display
        st.markdown(f"""
            <div class="top-pnl-card">
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><span style="font-size: 12px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 18px; font-weight: bold;">{t_trades}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span style="font-size: 18px; font-weight: bold;">{RUPEE}{t_gross:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{t_charges:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{t_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.dataframe(norm_bt, use_container_width=True, hide_index=True)

    # --- REVERSAL STRATEGY BACKTEST RESULTS ---
    if rev_bt is not None and not rev_bt.empty:
        st.markdown("---")
        st.markdown("#### 🔴 Reversal Strategy Backtest Summary")
        
        r_trades = len(rev_bt)
        r_gross = rev_bt["GrossPnL"].sum()
        r_charges = rev_bt["Charges"].sum()
        r_net = round(r_gross - r_charges, 2)
        r_net_class = "metric-val-green" if r_net >= 0 else "metric-val-red"

        # Summary Card Display
        st.markdown(f"""
            <div class="top-pnl-card">
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><span style="font-size: 12px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 18px; font-weight: bold;">{r_trades}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span style="font-size: 18px; font-weight: bold;">{RUPEE}{r_gross:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{r_charges:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{r_net_class}">{RUPEE}{r_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.dataframe(rev_bt, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 🗄️ All Live & Closed Trades Master Database")
    db_df = load_db()
    st.dataframe(db_df, use_container_width=True, hide_index=True)
