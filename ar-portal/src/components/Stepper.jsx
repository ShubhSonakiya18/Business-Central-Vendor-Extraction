// Stepper component used across Vendor and Customer flows
// steps: array of { label }
// currentStep: 0-indexed active step
// completedUpTo: number of steps fully completed (0-indexed exclusive)

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
       strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20,6 9,17 4,12"/>
  </svg>
)

export default function Stepper({ steps, currentStep }) {
  return (
    <div className="stepper" role="list" aria-label="Progress steps">
      {steps.map((step, index) => {
        const isCompleted = index < currentStep
        const isActive    = index === currentStep
        const isUpcoming  = index > currentStep

        let circleClass = 'step-circle '
        let labelClass  = 'step-label '

        if (isCompleted) { circleClass += 'step-circle--completed'; labelClass += 'step-label--completed' }
        if (isActive)    { circleClass += 'step-circle--active';    labelClass += 'step-label--active' }
        if (isUpcoming)  { circleClass += 'step-circle--upcoming';  labelClass += 'step-label--upcoming' }

        return (
          <div key={step.label} style={{ display: 'contents' }}>
            <div className="stepper-item" role="listitem">
              <div className={circleClass}
                   aria-label={`Step ${index + 1} ${step.label}: ${isCompleted ? 'completed' : isActive ? 'current' : 'upcoming'}`}
                   aria-current={isActive ? 'step' : undefined}>
                {isCompleted ? <CheckIcon /> : index + 1}
              </div>
              <span className={labelClass}>{step.label}</span>
            </div>
            {index < steps.length - 1 && (
              <div className={`stepper-connector${isCompleted ? ' stepper-connector--completed' : ''}`}
                   aria-hidden="true" />
            )}
          </div>
        )
      })}
    </div>
  )
}
