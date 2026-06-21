/**
 * components/chat/InlineChart.jsx
 * ================================
 * Renders a Chart.js chart inside a bot message when the response
 * includes chart data. Chart.js is loaded lazily from CDN.
 */
import { useRef, useEffect } from 'react'

export default function InlineChart({ chartData }) {
  const canvasRef = useRef(null)
  const chartRef  = useRef(null)

  useEffect(() => {
    if (!chartData || !canvasRef.current) return

    function renderChart() {
      if (chartRef.current) chartRef.current.destroy()
      const ctx = canvasRef.current.getContext('2d')
      chartRef.current = new window.Chart(ctx, {
        type: chartData.type || 'bar',
        data: {
          labels:   chartData.labels   || [],
          datasets: chartData.datasets || [],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: { font: { size: 12 }, color: 'var(--text-color)' },
            },
            title: {
              display: !!chartData.title,
              text:    chartData.title,
              color:   'var(--text-color)',
              font:    { size: 13, weight: '600' },
            },
          },
          scales: chartData.type === 'doughnut' ? {} : {
            x: {
              ticks: {
                color:        'var(--secondary-text)',
                font:         { size: 11 },
                maxTicksLimit: 8,          // never show more than 8 x-axis labels
                autoSkip:     true,
                maxRotation:  45,
                minRotation:  0,
              },
              grid: { color: 'var(--border-color)' },
            },
            y: {
              ticks: { color: 'var(--secondary-text)', font: { size: 11 } },
              grid:  { color: 'var(--border-color)' },
            },
          },
        },
      })
    }

    if (window.Chart) {
      renderChart()
    } else {
      const script = document.createElement('script')
      script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js'
      script.onload = renderChart
      document.head.appendChild(script)
    }

    return () => {
      if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null }
    }
  }, [chartData])

  if (!chartData) return null
  return (
    <div className="inline-chart-wrap">
      <canvas ref={canvasRef} />
    </div>
  )
}
