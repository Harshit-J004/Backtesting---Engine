import React, { useState, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Area, AreaChart, Cell } from 'recharts';
import { Upload, TrendingUp, TrendingDown, DollarSign, Clock, AlertCircle } from 'lucide-react';

const TradingBacktestAnalysis = () => {
    const [basketData, setBasketData] = useState([]);
    const [tradeData, setTradeData] = useState([]);
    const [equityData, setEquityData] = useState([]);
    const [activeTab, setActiveTab] = useState('overview');

    const handleFileUpload = (event, dataType) => {
        const file = event.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                const text = e.target.result;
                const rows = text.split('\n');
                const headers = rows[0].split(',');
                const data = rows.slice(1).filter(row => row.trim()).map(row => {
                    const values = row.split(',');
                    const obj = {};
                    headers.forEach((header, idx) => {
                        obj[header.trim()] = values[idx]?.trim();
                    });
                    return obj;
                });

                if (dataType === 'basket') setBasketData(data);
                else if (dataType === 'trade') setTradeData(data);
                else if (dataType === 'equity') setEquityData(data);
            };
            reader.readAsText(file);
        }
    };

    const verifyCommissionSlippage = () => {
        if (tradeData.length === 0) return null;

        const analysis = tradeData.map(trade => {
            const lotSize = parseFloat(trade.lot_size);
            const slippagePips = parseFloat(trade.slippage_pips);

            // Commission: Crypto Standard (0.02% per side = ~0.04% round trip)
            // Estimation: LotSize * Price (~$40k avg) * 0.0004
            // Since we don't have exact price here, we use a conservative $40k BTC avg
            const avgBtcPrice = 40000;
            const expectedCommission = (lotSize * avgBtcPrice) * 0.0004;

            // Slippage cost per pip per lot
            const slippageCost = Math.abs(slippagePips) * lotSize * 100000 * 0.0001;

            return {
                ...trade,
                lotSize,
                slippagePips,
                expectedCommission,
                slippageCost
            };
        });

        return analysis;
    };

    const calculateStats = () => {
        if (basketData.length === 0) return null;

        const netPnls = basketData.map(b => parseFloat(b.net_pnl));
        // Use duration_seconds if available, else fallback to minutes * 60
        const durations = basketData.map(b => {
            if (b.duration_seconds) return parseFloat(b.duration_seconds);
            return parseFloat(b.duration_minutes || 0) * 60;
        });

        const wins = netPnls.filter(p => p > 0);
        const losses = netPnls.filter(p => p <= 0);

        const totalPnl = netPnls.reduce((a, b) => a + b, 0);
        const avgWin = wins.length > 0 ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
        const avgLoss = losses.length > 0 ? losses.reduce((a, b) => a + b, 0) / losses.length : 0;
        const winRate = (wins.length / netPnls.length) * 100;

        const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length;
        const maxDuration = Math.max(...durations);

        return {
            totalPnl,
            avgWin,
            avgLoss,
            winRate,
            avgDuration, // In seconds
            maxDuration, // In seconds
            totalTrades: basketData.length,
            wins: wins.length,
            losses: losses.length
        };
    };

    // Helper to format duration
    const formatDuration = (seconds) => {
        if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
        if (seconds < 60) return `${seconds.toFixed(1)}s`;
        if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
        return `${(seconds / 3600).toFixed(1)}h`;
    };

    // Prepare equity curve data
    const prepareEquityCurve = () => {
        if (equityData.length === 0) return [];

        let runningEquity = parseFloat(equityData[0].capital) || 10000;
        let peak = runningEquity;

        return equityData.map((row, idx) => {
            const equity = parseFloat(row.total_equity) || runningEquity;
            peak = Math.max(peak, equity);
            const drawdown = ((equity - peak) / peak) * 100;

            return {
                date: row.date,
                equity: equity,
                drawdown: drawdown,
                peak: peak
            };
        });
    };

    // Prepare PnL distribution
    const preparePnLDistribution = () => {
        if (basketData.length === 0) return [];

        const bins = {};
        const binSize = 50;

        basketData.forEach(basket => {
            const pnl = parseFloat(basket.net_pnl);
            const bin = Math.floor(pnl / binSize) * binSize;
            bins[bin] = (bins[bin] || 0) + 1;
        });

        return Object.entries(bins)
            .map(([bin, count]) => ({
                range: `${bin} to ${parseInt(bin) + binSize}`,
                binStart: parseInt(bin),
                count
            }))
            .sort((a, b) => a.binStart - b.binStart);
    };

    // Monthly returns heatmap data
    const prepareMonthlyReturns = () => {
        if (basketData.length === 0) return [];

        const monthlyData = {};

        basketData.forEach(basket => {
            const date = new Date(basket.date);
            const year = date.getFullYear();
            const month = date.getMonth();
            const key = `${year}-${month}`;

            if (!monthlyData[key]) {
                monthlyData[key] = {
                    year,
                    month,
                    monthName: date.toLocaleString('default', { month: 'short' }),
                    pnl: 0
                };
            }

            monthlyData[key].pnl += parseFloat(basket.net_pnl);
        });

        return Object.values(monthlyData);
    };

    const stats = calculateStats();
    const equityCurve = prepareEquityCurve();
    const pnlDistribution = preparePnLDistribution();
    const monthlyReturns = prepareMonthlyReturns();
    const commissionAnalysis = verifyCommissionSlippage();

    const tabs = [
        { id: 'overview', label: 'Overview' },
        { id: 'equity', label: 'Equity & Drawdown' },
        { id: 'distribution', label: 'P&L Distribution' },
        { id: 'monthly', label: 'Monthly Returns' },
        { id: 'verification', label: 'Cost Verification' }
    ];

    return (
        <div className="w-full max-w-7xl mx-auto p-6 bg-gray-50">
            <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
                <h1 className="text-4xl font-bold mb-8 text-center text-gray-800">Trading Backtest Analysis Dashboard</h1>

                {/* File Upload Section */}
                <div className="grid grid-cols-1 gap-6 mb-8">
                    <div className="border-2 border-dashed border-gray-200 rounded-lg p-10 hover:border-blue-500 transition-colors group cursor-pointer">
                        <label className="flex flex-col items-center justify-center cursor-pointer w-full h-full">
                            <Upload className="w-12 h-12 text-gray-300 group-hover:text-blue-500 mb-4 transition-colors" />
                            <span className="text-xl font-medium text-gray-600 mb-2">Upload Basket Summary</span>
                            <span className="text-sm text-gray-400">
                                {basketData.length > 0 ? `✓ ${basketData.length} records loaded` : 'basket_summary_realistic.csv'}
                            </span>
                            <input
                                type="file"
                                accept=".csv"
                                onChange={(e) => handleFileUpload(e, 'basket')}
                                className="hidden"
                            />
                        </label>
                    </div>

                    <div className="border-2 border-dashed border-gray-200 rounded-lg p-10 hover:border-blue-500 transition-colors group cursor-pointer">
                        <label className="flex flex-col items-center justify-center cursor-pointer w-full h-full">
                            <Upload className="w-12 h-12 text-gray-300 group-hover:text-blue-500 mb-4 transition-colors" />
                            <span className="text-xl font-medium text-gray-600 mb-2">Upload Trade Log</span>
                            <span className="text-sm text-gray-400">
                                {tradeData.length > 0 ? `✓ ${tradeData.length} records loaded` : 'trade_log_realistic.csv'}
                            </span>
                            <input
                                type="file"
                                accept=".csv"
                                onChange={(e) => handleFileUpload(e, 'trade')}
                                className="hidden"
                            />
                        </label>
                    </div>

                    <div className="border-2 border-dashed border-gray-200 rounded-lg p-10 hover:border-blue-500 transition-colors group cursor-pointer">
                        <label className="flex flex-col items-center justify-center cursor-pointer w-full h-full">
                            <Upload className="w-12 h-12 text-gray-300 group-hover:text-blue-500 mb-4 transition-colors" />
                            <span className="text-xl font-medium text-gray-600 mb-2">Upload Equity Curve</span>
                            <span className="text-sm text-gray-400">
                                {equityData.length > 0 ? `✓ ${equityData.length} records loaded` : 'equity_curve_realistic.csv'}
                            </span>
                            <input
                                type="file"
                                accept=".csv"
                                onChange={(e) => handleFileUpload(e, 'equity')}
                                className="hidden"
                            />
                        </label>
                    </div>
                </div>

                {/* Tabs */}
                <div className="flex justify-center border-b border-gray-200 mb-8 overflow-x-auto">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`px-6 py-4 text-lg font-medium transition-colors whitespace-nowrap ${activeTab === tab.id
                                ? 'border-b-4 border-blue-500 text-blue-600'
                                : 'text-gray-500 hover:text-gray-800'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>

                {/* Content */}
                {activeTab === 'overview' && stats && (
                    <div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                            <div className="bg-blue-50 p-4 rounded-lg">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-gray-600">Total P&L</span>
                                    <DollarSign className="w-5 h-5 text-blue-600" />
                                </div>
                                <div className={`text-2xl font-bold ${stats.totalPnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                    ${stats.totalPnl.toFixed(2)}
                                </div>
                            </div>

                            <div className="bg-green-50 p-4 rounded-lg">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-gray-600">Win Rate</span>
                                    <TrendingUp className="w-5 h-5 text-green-600" />
                                </div>
                                <div className="text-2xl font-bold text-green-600">
                                    {stats.winRate.toFixed(1)}%
                                </div>
                                <div className="text-xs text-gray-500 mt-1">
                                    {stats.wins}W / {stats.losses}L
                                </div>
                            </div>

                            <div className="bg-purple-50 p-4 rounded-lg">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-gray-600">Avg Duration</span>
                                    <Clock className="w-5 h-5 text-purple-600" />
                                </div>
                                <div className="text-2xl font-bold text-purple-600">
                                    {formatDuration(stats.avgDuration)}
                                </div>
                                <div className="text-xs text-gray-500 mt-1">
                                    Max: {formatDuration(stats.maxDuration)}
                                </div>
                            </div>

                            <div className="bg-orange-50 p-4 rounded-lg">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-gray-600">Avg Win/Loss</span>
                                    <TrendingDown className="w-5 h-5 text-orange-600" />
                                </div>
                                <div className="text-sm font-bold text-green-600">
                                    Win: ${stats.avgWin.toFixed(2)}
                                </div>
                                <div className="text-sm font-bold text-red-600">
                                    Loss: ${stats.avgLoss.toFixed(2)}
                                </div>
                            </div>
                        </div>

                        <div className="bg-gray-50 p-4 rounded-lg">
                            <h3 className="font-semibold mb-2">Key Metrics</h3>
                            <div className="grid grid-cols-2 gap-2 text-sm">
                                <div>Total Trades: <span className="font-semibold">{stats.totalTrades}</span></div>
                                <div>Win/Loss Ratio: <span className="font-semibold">{(Math.abs(stats.avgWin / stats.avgLoss)).toFixed(2)}</span></div>
                                <div>Expectancy: <span className="font-semibold">${((stats.avgWin * stats.winRate / 100) + (stats.avgLoss * (1 - stats.winRate / 100))).toFixed(2)}</span></div>
                            </div>
                        </div>
                    </div>
                )}

                {activeTab === 'equity' && (
                    <div className="space-y-6">
                        <div>
                            <h3 className="text-lg font-semibold mb-4">Equity Curve</h3>
                            <ResponsiveContainer width="100%" height={300}>
                                <AreaChart data={equityCurve}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                        dataKey="date"
                                        tick={{ fontSize: 12 }}
                                        angle={-45}
                                        textAnchor="end"
                                        height={80}
                                    />
                                    <YAxis />
                                    <Tooltip
                                        formatter={(value) => `$${value.toFixed(2)}`}
                                    />
                                    <Legend />
                                    <Area
                                        type="monotone"
                                        dataKey="equity"
                                        stroke="#3b82f6"
                                        fill="#93c5fd"
                                        name="Equity"
                                    />
                                    <Area
                                        type="monotone"
                                        dataKey="peak"
                                        stroke="#10b981"
                                        fill="none"
                                        strokeDasharray="5 5"
                                        name="Peak"
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>

                        <div>
                            <h3 className="text-lg font-semibold mb-4">Drawdown Curve</h3>
                            <ResponsiveContainer width="100%" height={300}>
                                <AreaChart data={equityCurve}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                        dataKey="date"
                                        tick={{ fontSize: 12 }}
                                        angle={-45}
                                        textAnchor="end"
                                        height={80}
                                    />
                                    <YAxis />
                                    <Tooltip
                                        formatter={(value) => `${value.toFixed(2)}%`}
                                    />
                                    <Legend />
                                    <Area
                                        type="monotone"
                                        dataKey="drawdown"
                                        stroke="#ef4444"
                                        fill="#fca5a5"
                                        name="Drawdown %"
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                )}

                {activeTab === 'distribution' && (
                    <div className="space-y-6">
                        <div>
                            <h3 className="text-lg font-semibold mb-4">P&L Distribution</h3>
                            <ResponsiveContainer width="100%" height={400}>
                                <BarChart data={pnlDistribution}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                        dataKey="range"
                                        angle={-45}
                                        textAnchor="end"
                                        height={100}
                                        tick={{ fontSize: 10 }}
                                    />
                                    <YAxis />
                                    <Tooltip />
                                    <Legend />
                                    <Bar dataKey="count" name="Frequency">
                                        {pnlDistribution.map((entry, index) => (
                                            <Cell key={index} fill={entry.binStart >= 0 ? '#10b981' : '#ef4444'} />
                                        ))}
                                    </Bar>
                                </BarChart>
                            </ResponsiveContainer>
                        </div>

                        {basketData.length > 0 && (
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-green-50 p-4 rounded-lg">
                                    <h4 className="font-semibold text-green-800 mb-2">Winning Trades</h4>
                                    <div className="text-sm space-y-1">
                                        <div>Count: {basketData.filter(b => parseFloat(b.net_pnl) > 0).length}</div>
                                        <div>Total: ${basketData.filter(b => parseFloat(b.net_pnl) > 0).reduce((sum, b) => sum + parseFloat(b.net_pnl), 0).toFixed(2)}</div>
                                    </div>
                                </div>
                                <div className="bg-red-50 p-4 rounded-lg">
                                    <h4 className="font-semibold text-red-800 mb-2">Losing Trades</h4>
                                    <div className="text-sm space-y-1">
                                        <div>Count: {basketData.filter(b => parseFloat(b.net_pnl) <= 0).length}</div>
                                        <div>Total: ${basketData.filter(b => parseFloat(b.net_pnl) <= 0).reduce((sum, b) => sum + parseFloat(b.net_pnl), 0).toFixed(2)}</div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'monthly' && (
                    <div>
                        <h3 className="text-lg font-semibold mb-4">Monthly Returns Heatmap</h3>
                        <div className="overflow-x-auto">
                            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))' }}>
                                {monthlyReturns.map((month, idx) => (
                                    <div
                                        key={idx}
                                        className="p-3 rounded text-center"
                                        style={{
                                            backgroundColor: month.pnl > 0
                                                ? `rgba(16, 185, 129, ${Math.min(Math.abs(month.pnl) / 500, 1)})`
                                                : `rgba(239, 68, 68, ${Math.min(Math.abs(month.pnl) / 500, 1)})`
                                        }}
                                    >
                                        <div className="text-xs font-semibold text-white">
                                            {month.monthName} {month.year}
                                        </div>
                                        <div className="text-sm font-bold text-white mt-1">
                                            ${month.pnl.toFixed(0)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {activeTab === 'verification' && commissionAnalysis && (
                    <div>
                        <h3 className="text-lg font-semibold mb-4">Commission & Slippage Verification</h3>

                        <div className="bg-blue-50 border-l-4 border-blue-500 p-4 mb-6">
                            <div className="flex items-start">
                                <AlertCircle className="w-5 h-5 text-blue-600 mr-2 mt-0.5" />
                                <div className="text-sm">
                                    <p className="font-semibold text-blue-800 mb-1">Commission Formula (Crypto Standard):</p>
                                    <p className="text-blue-700">Round-trip commission = ~0.04% of Notional Value (0.02% Entry + 0.02% Exit)</p>
                                    <p className="text-blue-700 mt-1">Estimation Used: Lot Size * $40,000 (Avg BTC Price) * 0.0004</p>
                                </div>
                            </div>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                                <thead className="bg-gray-50">
                                    <tr>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Basket ID</th>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Trade #</th>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Lot Size</th>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Expected Commission</th>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Slippage (pips)</th>
                                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Slippage Cost ($)</th>
                                    </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-gray-200">
                                    {commissionAnalysis.slice(0, 20).map((trade, idx) => (
                                        <tr key={idx} className="hover:bg-gray-50">
                                            <td className="px-4 py-2 text-sm">{trade.basket_id}</td>
                                            <td className="px-4 py-2 text-sm">{trade.trade_num}</td>
                                            <td className="px-4 py-2 text-sm font-semibold">{trade.lotSize}</td>
                                            <td className="px-4 py-2 text-sm text-green-600">${trade.expectedCommission.toFixed(2)}</td>
                                            <td className="px-4 py-2 text-sm">{trade.slippagePips.toFixed(2)}</td>
                                            <td className="px-4 py-2 text-sm text-orange-600">${trade.slippageCost.toFixed(2)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        {commissionAnalysis.length > 20 && (
                            <p className="text-sm text-gray-500 mt-4 text-center">
                                Showing first 20 of {commissionAnalysis.length} trades
                            </p>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default TradingBacktestAnalysis;
