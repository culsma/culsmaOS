"""User-facing interpretation of existing run facts; never a recovery authority."""


class RunGuidanceInteractor:
    def describe(self, run):
        status=run.get('status')
        evidence=run.get('execution_evidence')
        recorded=(isinstance(evidence,dict) and evidence.get('schema')=='culsma_run_evidence_v1'
                  and evidence.get('accounting')=='recorded' and isinstance(evidence.get('attempts'),list))
        attempts=evidence['attempts'] if recorded else None
        result=run.get('result') if isinstance(run.get('result'),dict) else {}
        state=result.get('os') if isinstance(result.get('os'),dict) else {}
        unresolved=state.get('unresolved_material_effects')
        before_execution=status in {'failed','rejected'} and attempts==[] and not unresolved
        error=run.get('error') if isinstance(run.get('error'),str) else ''
        summary={'schema':'culsma_run_guidance_v1','kind':'information','actions':[],
                 'device_activity':'none_recorded' if before_execution else 'recorded' if attempts else 'unverified'}
        faults = self.faults(run, attempts)
        if status != 'completed' and faults:
            return self.fault_guidance(summary, faults, before_execution, status in {'needs_reconciliation','reconciliation_required','quarantined'} or bool(unresolved))
        if status=='completed':
            return {**summary,'title':'Experiment complete','message':'The experiment finished. Review the recorded results below.',
                    'next_steps':[]}
        if status in {'needs_reconciliation','reconciliation_required','quarantined'} or unresolved:
            return {**summary,'kind':'attention','title':'Check the station before continuing',
                    'message':'The outcome of an operation is uncertain. Check the device and execution records before deciding what to do next.',
                    'next_steps':['Keep the affected equipment and materials unchanged until the outcome is reviewed.'],
                    'actions':['open_workstation']}
        if before_execution and self.tip_shortage(error):
            return {**summary,'kind':'preparation','title':'More tips are needed',
                    'message':'There were not enough available tips to prepare this attempt. Update the tip supply before starting a new run.',
                    'next_steps':['Replace or replenish the tip box at the workstation.',
                                  'Check supplies again, then open the protocol from Files to start a new run.'],
                    'actions':['replace_tips','refresh','open_files']}
        if before_execution and error.startswith(('BATCH_PREPARATION_REJECTED','PREFLIGHT_','SETUP_')):
            return {**summary,'kind':'preparation','title':'The setup needs attention',
                    'message':'The station could not prepare this experiment. Check the layout, supplies and device configuration.',
                    'next_steps':['Review the workstation and correct the setup before starting a new run.'],
                    'actions':['open_workstation','refresh','open_files']}
        if before_execution:
            return {**summary,'kind':'preparation','title':'The experiment could not start',
                    'message':'Check the program and workstation setup. Technical details are available below if you need more information.',
                    'next_steps':['Correct the program or preparation, then start a new run from Files.'],
                    'actions':['open_workstation','refresh','open_files']}
        if status in {'failed','rejected'}:
            return {**summary,'kind':'attention','title':'The experiment stopped',
                    'message':'The experiment did not finish. Some operations may already have taken place.',
                    'next_steps':['Check the workstation and execution records before starting another run.'],
                    'actions':['open_workstation','refresh']}
        titles={'awaiting_setup':'Prepare the experiment','paused':'Experiment paused','cancelled':'Experiment cancelled',
                'queued':'Waiting for the station','ready':'Preparing the experiment','waiting':'Experiment running',
                'running':'Experiment running','finalizing':'Finishing the experiment'}
        messages={'awaiting_setup':'Review the loading plan, prepare the listed items and confirm when they are ready.',
                  'paused':'The experiment is paused. Completed work remains recorded.',
                  'cancelled':'Further work was cancelled. Review the record for any operations already completed.'}
        return {**summary,'title':titles.get(status,'Checking the experiment'),
                'message':messages.get(status,'Follow the run controls and status below.'),'next_steps':[]}

    def tip_shortage(self, error):
        # Older stored records retained a driver message rather than its typed code.
        # Interpret only known preparation diagnostics, never arbitrary substring matches.
        detail=error
        for prefix in ('BATCH_PREPARATION_REJECTED: ','PRE_DISPATCH_REJECTED: ','GROUP_PRE_DISPATCH_REJECTED: '):
            if detail.startswith(prefix):
                detail=detail.removeprefix(prefix)
                break
        return (detail in {'TRANSFER_TIPS_EXHAUSTED','RESOURCE_CONSUMABLES_INSUFFICIENT'}
                or detail.startswith('No available tip positions are declared for this run.')
                or detail.startswith('Insufficient tips') or detail.startswith('Not enough tips'))


    def faults(self, run, attempts):
        from culsma_os.driver_framework.interactors import DeviceFaultInteractor
        result_data = run.get('result') if isinstance(run.get('result'), dict) else {}
        result = list(result_data.get('os', {}).get('faults', ()))
        for attempt in attempts or ():
            receipt = attempt.get('evidence') or {}
            result.extend(receipt.get('payload', {}).get('faults', ()))
        try:
            return DeviceFaultInteractor().validate(result)
        except (ValueError, TypeError, KeyError):
            return ()

    def fault_guidance(self, summary, faults, before_execution, isolated):
        fault = faults[-1]
        simulated = fault['source'] == 'simulation'
        titles = {'TIP_UNAVAILABLE':'Tips need attention', 'LIQUID_INSUFFICIENT':'The liquid supply needs attention',
                  'LIQUID_NOT_DETECTED':'Liquid was not detected', 'DEVICE_NOT_READY':'The device is not ready',
                  'COMMUNICATION_LOST':'The device connection needs attention', 'DEVICE_ERROR':'The device reported a problem'}
        steps = {'TIP_UNAVAILABLE':'Check the tip rack and pipette. Replace tips manually if needed.',
                 'LIQUID_INSUFFICIENT':'Check the source amount and transfer volume before continuing.',
                 'LIQUID_NOT_DETECTED':'Check the liquid, container position and liquid-detection settings.',
                 'DEVICE_NOT_READY':'Check the indicated module, plate position and device status.',
                 'COMMUNICATION_LOST':'Check the device and connection. A lost reply does not establish whether an action finished.',
                 'DEVICE_ERROR':'Inspect the device and its original error record.'}
        message = ('The local simulation reported this condition. No physical inspection was performed.' if simulated
                   else 'The driver reported this condition. Inspect the device before deciding how to proceed.')
        next_steps = (["Review the declared loading plan and device settings."] if simulated else [steps[fault['code']]])
        if isolated:
            next_steps.append('Execution remains isolated. An acknowledgement does not authorize repeating an action or resuming the device.')
        return {**summary, 'kind':'preparation' if before_execution else 'attention',
                'title':titles[fault['code']], 'message':message, 'faults':list(faults),
                'next_steps':next_steps, 'actions':['open_workstation','refresh']}
