import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import math
import json

# Page configuration
st.set_page_config(
    page_title="🏠 House Affordability Calculator",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Utility functions
def to_currency(amount):
    """Format number as currency"""
    return f"${amount:,.2f}"

def to_percent(rate):
    """Format number as percentage"""
    return f"{rate:.2f}%"

def clamp(value, min_val, max_val):
    """Clamp value between min and max"""
    return max(min_val, min(value, max_val))

def safe_divide(numerator, denominator):
    """Safe division that returns 0 if denominator is 0"""
    return numerator / denominator if denominator != 0 else 0

def pmt(rate, nper, pv):
    """Calculate monthly payment using standard mortgage formula"""
    if rate == 0:
        return pv / nper
    return rate * pv / (1 - (1 + rate) ** -nper)

def invert_pmt(payment, rate, nper):
    """Calculate loan amount from monthly payment"""
    if rate == 0:
        return payment * nper
    return payment * (1 - (1 + rate) ** -nper) / rate

@st.cache_data
def make_amortization_schedule(loan_amount, annual_rate, years):
    """Create amortization schedule"""
    monthly_rate = annual_rate / 100 / 12
    total_months = int(years * 12)
    monthly_payment = pmt(monthly_rate, total_months, loan_amount)
    
    schedule = []
    balance = loan_amount
    cumulative_interest = 0
    
    for month in range(1, total_months + 1):
        interest = balance * monthly_rate
        principal = monthly_payment - interest
        balance = max(0, balance - principal)
        cumulative_interest += interest
        
        schedule.append({
            'Month': month,
            'Beginning Balance': balance + principal,
            'Interest': interest,
            'Principal': principal,
            'Ending Balance': balance,
            'Cumulative Interest': cumulative_interest
        })
        
        if balance <= 0:
            break
    
    return pd.DataFrame(schedule)

def calculate_risk_score(back_end_dti, ltv, credit_score_band):
    """Calculate risk score (0-100) based on weighted factors"""
    # DTI risk (50% weight) - higher DTI = higher risk
    dti_risk = min(back_end_dti / 0.5, 1.0)  # Scale so 50% DTI = max risk
    
    # LTV risk (30% weight) - higher LTV = higher risk
    ltv_risk = min(ltv / 1.0, 1.0)  # Scale so 100% LTV = max risk
    
    # Credit score risk (20% weight) - lower score = higher risk
    credit_risks = {
        "760+": 0.1,
        "720-759": 0.3,
        "680-719": 0.5,
        "640-679": 0.7,
        "Under 640": 1.0
    }
    credit_risk = credit_risks.get(credit_score_band, 0.5)
    
    # Weighted combination
    risk_score = (dti_risk * 0.5 + ltv_risk * 0.3 + credit_risk * 0.2) * 100
    return min(100, max(0, risk_score))

def get_risk_label_and_color(risk_score):
    """Get risk label and color based on score"""
    if risk_score < 25:
        return "Low", "#28a745"
    elif risk_score < 50:
        return "Moderate", "#ffc107"
    elif risk_score < 75:
        return "High", "#fd7e14"
    else:
        return "Very High", "#dc3545"

def get_risk_guidance(risk_label, ltv, back_end_dti):
    """Provide risk-specific guidance"""
    if risk_label == "Low":
        return "✅ Good financial position for homeownership"
    elif risk_label == "Moderate":
        if ltv > 0.8:
            return "💡 Consider increasing down payment to reduce PMI and LTV"
        return "💡 Monitor debt levels and consider building emergency fund"
    elif risk_label == "High":
        if back_end_dti > 0.36:
            return "⚠️ Consider reducing debt or increasing income before buying"
        return "⚠️ Consider a smaller home price or larger down payment"
    else:
        return "🚨 High risk - strongly consider improving financial position first"

# Initialize session state
if 'scenarios' not in st.session_state:
    st.session_state.scenarios = []

# Sidebar inputs
st.sidebar.title("🏠 Mortgage Calculator")

# Basic financial inputs
annual_income = st.sidebar.number_input(
    "Annual Gross Income", 
    min_value=1000, 
    value=80000, 
    step=5000,
    help="Your total annual income before taxes"
)

existing_debt = st.sidebar.number_input(
    "Existing Monthly Debts", 
    min_value=0, 
    value=500, 
    step=50,
    help="Monthly payments for credit cards, loans, etc."
)

credit_score = st.sidebar.selectbox(
    "Credit Score Range",
    ["760+", "720-759", "680-719", "640-679", "Under 640"],
    index=1
)

# Home price or affordability mode
price_mode = st.sidebar.radio(
    "Calculation Mode",
    ["Set Home Price", "Find Max Affordability"]
)

if price_mode == "Set Home Price":
    home_price = st.sidebar.number_input(
        "Home Price", 
        min_value=1000, 
        value=400000, 
        step=10000
    )
else:
    home_price = None

# Down payment inputs
col1, col2 = st.sidebar.columns(2)
with col1:
    down_payment_amount = st.number_input(
        "Down Payment ($)", 
        min_value=0, 
        value=80000 if home_price else 60000, 
        step=5000
    )
with col2:
    down_payment_percent = st.number_input(
        "Down Payment (%)", 
        min_value=0.0, 
        max_value=100.0, 
        value=20.0, 
        step=0.5
    )

# Sync down payment amount and percent
if home_price:
    if st.sidebar.button("Sync % → $"):
        down_payment_amount = home_price * down_payment_percent / 100
        st.rerun()
    if st.sidebar.button("Sync $ → %"):
        down_payment_percent = (down_payment_amount / home_price) * 100
        st.rerun()

# Loan terms
interest_rate = st.sidebar.number_input(
    "Interest Rate (%)", 
    min_value=0.1, 
    max_value=20.0, 
    value=6.5, 
    step=0.25
)

loan_term = st.sidebar.selectbox(
    "Loan Term (Years)",
    [15, 20, 30],
    index=2
)

# Property costs
property_tax_rate = st.sidebar.number_input(
    "Property Tax Rate (%)", 
    min_value=0.0, 
    max_value=5.0, 
    value=1.2, 
    step=0.1
)

home_insurance = st.sidebar.number_input(
    "Home Insurance (Annual)", 
    min_value=0, 
    value=1200, 
    step=100
)

hoa_fees = st.sidebar.number_input(
    "HOA Fees (Monthly)", 
    min_value=0, 
    value=0, 
    step=50
)

pmi_rate = st.sidebar.number_input(
    "PMI Rate (%)", 
    min_value=0.0, 
    max_value=2.0, 
    value=0.5, 
    step=0.1,
    help="Applied when down payment < 20%"
)

closing_costs_percent = st.sidebar.number_input(
    "Closing Costs (%)", 
    min_value=0.0, 
    max_value=10.0, 
    value=3.0, 
    step=0.5
)

# DTI limits
max_front_dti = st.sidebar.number_input(
    "Max Front-End DTI (%)", 
    min_value=10.0, 
    max_value=50.0, 
    value=28.0, 
    step=1.0
) / 100

max_back_dti = st.sidebar.number_input(
    "Max Back-End DTI (%)", 
    min_value=10.0, 
    max_value=60.0, 
    value=36.0, 
    step=1.0
) / 100

# Sensitivity analysis
st.sidebar.subheader("Sensitivity Analysis")
rate_step = st.sidebar.number_input(
    "Rate Step (%)", 
    min_value=0.1, 
    max_value=2.0, 
    value=0.25, 
    step=0.05
)

dp_step = st.sidebar.number_input(
    "Down Payment Step (%)", 
    min_value=0.5, 
    max_value=10.0, 
    value=2.0, 
    step=0.5
)

# Action buttons
if st.sidebar.button("Save Scenario"):
    scenario = {
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'annual_income': annual_income,
        'home_price': home_price,
        'down_payment_amount': down_payment_amount,
        'interest_rate': interest_rate,
        'loan_term': loan_term,
        'monthly_payment': None,  # Will be calculated
        'back_end_dti': None,    # Will be calculated
        'ltv': None              # Will be calculated
    }
    st.session_state.scenarios.append(scenario)
    if len(st.session_state.scenarios) > 2:
        st.session_state.scenarios.pop(0)
    st.sidebar.success("Scenario saved!")

if st.sidebar.button("Reset Inputs"):
    st.rerun()

# Core calculations
monthly_income = annual_income / 12

# Calculate based on mode
if price_mode == "Set Home Price" and home_price:
    # User set price - calculate affordability
    loan_amount = home_price - down_payment_amount
    
    # Validate down payment
    if down_payment_amount >= home_price:
        st.error("Down payment cannot be greater than or equal to home price")
        st.stop()
    
    # Monthly P&I
    monthly_rate = interest_rate / 100 / 12
    total_months = loan_term * 12
    monthly_pi = pmt(monthly_rate, total_months, loan_amount)
    
    # Other monthly costs
    monthly_tax = home_price * property_tax_rate / 100 / 12
    monthly_insurance = home_insurance / 12
    monthly_hoa = hoa_fees
    
    # PMI if down payment < 20%
    monthly_pmi = 0
    if down_payment_percent < 20:
        monthly_pmi = loan_amount * pmi_rate / 100 / 12
    
    total_monthly_payment = monthly_pi + monthly_tax + monthly_insurance + monthly_hoa + monthly_pmi
    
    # DTI calculations
    front_end_dti = total_monthly_payment / monthly_income
    back_end_dti = (total_monthly_payment + existing_debt) / monthly_income
    
    # LTV
    ltv = loan_amount / home_price
    
    max_affordable_price = home_price  # Same as set price
    
else:
    # Find maximum affordability
    # Max payment based on DTI constraints
    max_payment_front = monthly_income * max_front_dti
    max_payment_back = monthly_income * max_back_dti - existing_debt
    max_payment_constraint = min(max_payment_front, max_payment_back)
    
    # Estimate other costs as percentage of price to solve iteratively
    # Assume price P, then other costs are functions of P
    # Total payment = PI + Tax + Insurance + HOA + PMI
    # PI comes from loan amount = P - down_payment
    
    # Iterative solution for maximum price
    estimated_price = 400000  # Starting guess
    for _ in range(10):  # Iterate to converge
        estimated_loan = estimated_price - down_payment_amount
        monthly_rate = interest_rate / 100 / 12
        total_months = loan_term * 12
        
        if estimated_loan <= 0:
            estimated_price = down_payment_amount * 2
            continue
            
        monthly_pi = pmt(monthly_rate, total_months, estimated_loan)
        monthly_tax = estimated_price * property_tax_rate / 100 / 12
        monthly_insurance = home_insurance / 12
        monthly_hoa = hoa_fees
        
        monthly_pmi = 0
        if down_payment_amount / estimated_price < 0.20:
            monthly_pmi = estimated_loan * pmi_rate / 100 / 12
        
        estimated_total = monthly_pi + monthly_tax + monthly_insurance + monthly_hoa + monthly_pmi
        
        if abs(estimated_total - max_payment_constraint) < 10:
            break
        
        # Adjust price based on payment difference
        ratio = max_payment_constraint / estimated_total
        estimated_price *= ratio
    
    # Set calculated values
    home_price = max(estimated_price, down_payment_amount + 1000)
    max_affordable_price = home_price
    loan_amount = home_price - down_payment_amount
    
    # Recalculate final values
    monthly_pi = pmt(monthly_rate, total_months, loan_amount)
    monthly_tax = home_price * property_tax_rate / 100 / 12
    monthly_insurance = home_insurance / 12
    monthly_hoa = hoa_fees
    
    monthly_pmi = 0
    if down_payment_amount / home_price < 0.20:
        monthly_pmi = loan_amount * pmi_rate / 100 / 12
    
    total_monthly_payment = monthly_pi + monthly_tax + monthly_insurance + monthly_hoa + monthly_pmi
    front_end_dti = total_monthly_payment / monthly_income
    back_end_dti = (total_monthly_payment + existing_debt) / monthly_income
    ltv = loan_amount / home_price

# Risk assessment
risk_score = calculate_risk_score(back_end_dti, ltv, credit_score)
risk_label, risk_color = get_risk_label_and_color(risk_score)
risk_guidance = get_risk_guidance(risk_label, ltv, back_end_dti)

# Total interest over life
total_interest = (monthly_pi * loan_term * 12) - loan_amount

# Update scenario with calculated values
if st.session_state.scenarios:
    st.session_state.scenarios[-1].update({
        'monthly_payment': total_monthly_payment,
        'back_end_dti': back_end_dti,
        'ltv': ltv
    })

# Main layout
st.title("🏠 House Affordability & Mortgage Risk Calculator")

# Top summary cards
col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric("Home Price", to_currency(home_price))

with col2:
    st.metric("Loan Amount", to_currency(loan_amount))

with col3:
    st.metric("Monthly Payment", to_currency(total_monthly_payment))

with col4:
    st.metric("Back-End DTI", to_percent(back_end_dti * 100))

with col5:
    st.metric("LTV", to_percent(ltv * 100))

with col6:
    st.markdown(f"<div style='background-color: {risk_color}; color: white; padding: 10px; border-radius: 5px; text-align: center;'><strong>{risk_label} Risk</strong></div>", unsafe_allow_html=True)

# Warning messages
if down_payment_percent < 3:
    st.warning("⚠️ Many lenders require a minimum 3% down payment")

if back_end_dti > max_back_dti or front_end_dti > max_front_dti:
    st.error("❌ DTI exceeds recommended limits. Consider a lower price or higher down payment.")

st.markdown(f"**Risk Guidance:** {risk_guidance}")

# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Results", "📈 Charts", "ℹ️ Assumptions"])

with tab1:
    st.subheader("Payment Breakdown")
    
    # Payment components table
    payment_data = {
        'Component': ['Principal & Interest', 'Property Tax', 'Home Insurance', 'HOA Fees', 'PMI', 'Total'],
        'Monthly Amount': [
            to_currency(monthly_pi),
            to_currency(monthly_tax),
            to_currency(monthly_insurance),
            to_currency(monthly_hoa),
            to_currency(monthly_pmi),
            to_currency(total_monthly_payment)
        ]
    }
    
    payment_df = pd.DataFrame(payment_data)
    st.dataframe(payment_df, use_container_width=True)
    
    # DTI and affordability metrics
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Debt-to-Income Ratios")
        st.metric(
            "Front-End DTI", 
            to_percent(front_end_dti * 100),
            help="Housing payment ÷ Monthly income"
        )
        st.metric(
            "Back-End DTI", 
            to_percent(back_end_dti * 100),
            help="Total debt payments ÷ Monthly income"
        )
        st.metric("Monthly Income", to_currency(monthly_income))
    
    with col2:
        st.subheader("Loan Details")
        st.metric("Loan-to-Value", to_percent(ltv * 100))
        st.metric("Total Interest", to_currency(total_interest))
        st.metric("Closing Costs", to_currency(home_price * closing_costs_percent / 100))
    
    # Scenario comparison
    if len(st.session_state.scenarios) >= 2:
        st.subheader("Scenario Comparison")
        
        scenarios_df = pd.DataFrame(st.session_state.scenarios[-2:])
        scenarios_df.index = ['Previous', 'Current']
        
        comparison_cols = ['home_price', 'monthly_payment', 'back_end_dti', 'ltv']
        for col in comparison_cols:
            if col in scenarios_df.columns:
                scenarios_df[col] = scenarios_df[col].apply(
                    lambda x: to_currency(x) if 'price' in col or 'payment' in col 
                    else to_percent(x * 100) if 'dti' in col or 'ltv' in col 
                    else x
                )
        
        st.dataframe(scenarios_df[comparison_cols], use_container_width=True)

with tab2:
    # Payment composition pie chart
    st.subheader("Monthly Payment Composition")
    
    pie_data = {
        'Component': ['Principal & Interest', 'Property Tax', 'Insurance', 'HOA', 'PMI'],
        'Amount': [monthly_pi, monthly_tax, monthly_insurance, monthly_hoa, monthly_pmi]
    }
    
    pie_df = pd.DataFrame(pie_data)
    pie_df = pie_df[pie_df['Amount'] > 0]  # Remove zero components
    
    fig_pie = px.pie(pie_df, values='Amount', names='Component', 
                     title="Payment Breakdown")
    st.plotly_chart(fig_pie, use_container_width=True)
    
    # Loan balance over time
    st.subheader("Loan Balance Over Time")
    
    amortization = make_amortization_schedule(loan_amount, interest_rate, loan_term)
    
    # Show first 120 months prominently, rest faintly
    fig_balance = go.Figure()
    
    if len(amortization) > 120:
        # First 10 years
        fig_balance.add_trace(go.Scatter(
            x=amortization.iloc[:120]['Month'],
            y=amortization.iloc[:120]['Ending Balance'],
            mode='lines',
            name='First 10 Years',
            line=dict(width=3, color='blue')
        ))
        
        # Remaining years (faint)
        fig_balance.add_trace(go.Scatter(
            x=amortization.iloc[120:]['Month'],
            y=amortization.iloc[120:]['Ending Balance'],
            mode='lines',
            name='Remaining Years',
            line=dict(width=1, color='lightblue', dash='dot')
        ))
    else:
        fig_balance.add_trace(go.Scatter(
            x=amortization['Month'],
            y=amortization['Ending Balance'],
            mode='lines',
            name='Loan Balance',
            line=dict(width=3, color='blue')
        ))
    
    fig_balance.update_layout(
        title="Loan Balance Over Time",
        xaxis_title="Month",
        yaxis_title="Remaining Balance ($)",
        yaxis_tickformat="$,.0f"
    )
    
    st.plotly_chart(fig_balance, use_container_width=True)
    
    # Sensitivity analysis
    st.subheader("Sensitivity Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Interest Rate Impact on Affordable Price**")
        
        rates = [interest_rate - rate_step * 2, interest_rate - rate_step, 
                interest_rate, interest_rate + rate_step, interest_rate + rate_step * 2]
        prices = []
        
        for rate in rates:
            # Simplified calculation for sensitivity
            monthly_rate_sens = rate / 100 / 12
            max_pi = max_payment_constraint - (monthly_tax + monthly_insurance + monthly_hoa)
            if monthly_rate_sens > 0:
                max_loan_sens = invert_pmt(max_pi, monthly_rate_sens, loan_term * 12)
                max_price_sens = max_loan_sens + down_payment_amount
                prices.append(max_price_sens)
            else:
                prices.append(max_affordable_price)
        
        sens_df = pd.DataFrame({'Rate (%)': rates, 'Max Price ($)': prices})
        fig_rate = px.line(sens_df, x='Rate (%)', y='Max Price ($)', 
                          title="Rate vs Affordable Price")
        fig_rate.add_vline(x=interest_rate, line_dash="dash", 
                          annotation_text="Current Rate")
        st.plotly_chart(fig_rate, use_container_width=True)
    
    with col2:
        st.write("**Down Payment Impact on Monthly Payment**")
        
        dp_percents = [max(0, down_payment_percent - dp_step * 2),
                      max(0, down_payment_percent - dp_step),
                      down_payment_percent,
                      min(50, down_payment_percent + dp_step),
                      min(50, down_payment_percent + dp_step * 2)]
        
        payments = []
        for dp_pct in dp_percents:
            dp_amount_sens = home_price * dp_pct / 100
            loan_amount_sens = home_price - dp_amount_sens
            monthly_pi_sens = pmt(monthly_rate, total_months, loan_amount_sens)
            
            # PMI adjustment
            monthly_pmi_sens = 0
            if dp_pct < 20:
                monthly_pmi_sens = loan_amount_sens * pmi_rate / 100 / 12
            
            total_payment_sens = (monthly_pi_sens + monthly_tax + 
                                monthly_insurance + monthly_hoa + monthly_pmi_sens)
            payments.append(total_payment_sens)
        
        dp_df = pd.DataFrame({'Down Payment (%)': dp_percents, 'Monthly Payment ($)': payments})
        fig_dp = px.line(dp_df, x='Down Payment (%)', y='Monthly Payment ($)',
                        title="Down Payment vs Monthly Payment")
        fig_dp.add_vline(x=down_payment_percent, line_dash="dash",
                        annotation_text="Current Down Payment")
        st.plotly_chart(fig_dp, use_container_width=True)

with tab3:
    st.subheader("Calculations & Assumptions")
    
    st.markdown("""
    **Monthly Payment Formula:**
    ```
    M = r × L / (1 - (1 + r)^(-n))
    ```
    Where:
    - M = Monthly payment
    - r = Monthly interest rate (annual rate ÷ 12)
    - L = Loan amount
    - n = Total number of months
    
    **Debt-to-Income Ratios:**
    - **Front-End DTI:** Housing payment ÷ Monthly gross income
    - **Back-End DTI:** Total debt payments ÷ Monthly gross income
    
    **Loan-to-Value (LTV):** Loan amount ÷ Home price
    
    **PMI Application:** Applied when down payment < 20% of home price
    
    **Common Underwriting Standards:**
    - Maximum Front-End DTI: 28%
    - Maximum Back-End DTI: 36%
    - Minimum Down Payment: 3% (varies by loan type)
    - PMI removed when LTV reaches 78%
    
    **Risk Score Calculation:**
    - Back-End DTI: 50% weight
    - LTV: 30% weight  
    - Credit Score: 20% weight
    
    **Property Costs:**
    - Property tax calculated as annual percentage of home price
    - Insurance entered as annual premium, divided by 12
    - HOA fees as monthly amount
    """)

# Download options
st.subheader("Downloads")

col1, col2 = st.columns(2)

with col1:
    if st.button("Download Amortization Schedule"):
        csv = amortization.to_csv(index=False)
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"amortization_schedule_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

with col2:
    if st.button("Generate Report"):
        # Create HTML report
        report_html = f"""
        <html>
        <head><title>Mortgage Analysis Report</title></head>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
        <h1>🏠 Mortgage Analysis Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
        
        <h2>Summary</h2>
        <table border="1" cellpadding="10">
        <tr><td>Home Price</td><td>{to_currency(home_price)}</td></tr>
        <tr><td>Loan Amount</td><td>{to_currency(loan_amount)}</td></tr>
        <tr><td>Monthly Payment</td><td>{to_currency(total_monthly_payment)}</td></tr>
        <tr><td>Back-End DTI</td><td>{to_percent(back_end_dti * 100)}</td></tr>
        <tr><td>LTV</td><td>{to_percent(ltv * 100)}</td></tr>
        <tr><td>Risk Level</td><td style="color: {risk_color};">{risk_label}</td></tr>
        </table>
        
        <h2>Payment Breakdown</h2>
        <ul>
        <li>Principal & Interest: {to_currency(monthly_pi)}</li>
        <li>Property Tax: {to_currency(monthly_tax)}</li>
        <li>Insurance: {to_currency(monthly_insurance)}</li>
        <li>HOA: {to_currency(monthly_hoa)}</li>
        <li>PMI: {to_currency(monthly_pmi)}</li>
        </ul>
        
        <p><strong>Risk Guidance:</strong> {risk_guidance}</p>
        </body>
        </html>
        """
        
        st.download_button(
            label="📄 Download HTML Report",
            data=report_html,
            file_name=f"mortgage_report_{datetime.now().strftime('%Y%m%d')}.html",
            mime="text/html"
        )

# Smoke tests
if __name__ == "__main__":
    # Test basic payment calculation
    test_payment = pmt(0.065/12, 30*12, 320000)
    expected_payment = 2021.84  # Known value for 6.5%, 30yr, $320k loan
    
    print(f"Smoke Test - Payment Calculation:")
    print(f"  Calculated: ${test_payment:.2f}")
    print(f"  Expected: ${expected_payment:.2f}")
    print(f"  Difference: ${abs(test_payment - expected_payment):.2f}")
    print(f"  Test {'PASSED' if abs(test_payment - expected_payment) < 1.0 else 'FAILED'}")
    
    # Test risk score calculation
    test_risk = calculate_risk_score(0.36, 0.8, "720-759")
    print(f"\nSmoke Test - Risk Score:")
    print(f"  DTI: 36%, LTV: 80%, Credit: 720-759")
    print(f"  Risk Score: {test_risk:.1f}")
    print(f"  Test {'PASSED' if 30 <= test_risk <= 60 else 'FAILED'}")
