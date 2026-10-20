'use strict';
const fs=require('fs'),path=require('path'),cp=require('child_process'),os=require('os');
const SHA='cf0f913cc15c41705e803593297e89cd6056b839';
async function seed(input,out){
 const api=require('./dist/api.cjs');
 const analyses=[];
 for(const r of input.requirements){
  const parsed=api.compile(r.text);
  if(parsed.parseErrors||!parsed.collectedSemantics) throw Error(`${r.id}: ${parsed.parseErrors||'no semantics'}`);
  const s=parsed.collectedSemantics;
  if(s.component_name!==input.component) throw Error(`${r.id}: FRET component ${s.component_name} != ${input.component}`);
  for(const name of (s.variables||[]).filter(n=>n!=='FTP')) if(!input.variables.some(v=>v.name===name)) throw Error(`${r.id}: missing variable mapping for ${name}`);
  analyses.push({id:r.id,text:r.text,semantics:s});
  if(typeof s.diagram==='string') {
   if(s.diagram.includes('<svg')) fs.writeFileSync(path.join(out,r.id+'.svg'),s.diagram);
   else {
    const svg=path.resolve('/opt/probe/source/docs',s.diagram);
    if(svg.startsWith('/opt/probe/source/docs/')&&fs.existsSync(svg)) fs.copyFileSync(svg,path.join(out,r.id+'.svg'));
   }
  }
  await api.leveldbDB.put({_id:r.id,reqid:r.id,project:input.project,fulltext:r.text,semantics:s});
 }
 await api.modelDB.bulkDocs(input.variables.map((v,i)=>({_id:'var-'+i,project:input.project,component_name:input.component,variable_name:v.name,idType:v.role,dataType:v.type,completed:true,modeldoc:false,description:'',modelComponent:'',modeldoc_id:''})));
 fs.writeFileSync(path.join(out,'requirements-analysis.json'),JSON.stringify({sourceSHA:SHA,requirements:analyses},null,2));
 await api.leveldbDB.close();await api.modelDB.close();
}
async function main(){
 const [file,outArg]=process.argv.slice(2),out=path.resolve(outArg);
 fs.mkdirSync(out,{recursive:true});
 const input=JSON.parse(fs.readFileSync(file,'utf8'));
 if(!input.project||!input.component||!Array.isArray(input.requirements)||!input.requirements.length||!Array.isArray(input.variables)) throw Error('Expected project, component, requirements [{id,text}], variables [{name,role,type}]');
 for(const r of input.requirements) if(!/^[A-Za-z][A-Za-z0-9_]*$/.test(r.id)||typeof r.text!=='string') throw Error('Requirement id must be an identifier and text a string');
 if(new Set(input.requirements.map(r=>r.id)).size!==input.requirements.length) throw Error('Duplicate requirement ids');
 for(const v of input.variables) if(!['Input','Output'].includes(v.role)||!['boolean','integer','double'].includes(v.type)) throw Error('Supported roles: Input/Output; types: boolean/integer/double');
 if(process.env.PROBE_SEED==='1'){await seed(input,out);return;}
 const home=fs.mkdtempSync('/tmp/fret-probe-');
 const env={...process.env,HOME:home,PROBE_SOLVER_LOG_DIR:path.join(out,'solver-invocations')};
 fs.mkdirSync(path.join(home,'Documents'),{recursive:true});
 const seeded=cp.spawnSync(process.execPath,[__filename,file,out],{env:{...env,PROBE_SEED:'1'},encoding:'utf8',timeout:60000});
 fs.writeFileSync(path.join(out,'seed.log'),seeded.stdout+seeded.stderr);
 if(seeded.status!==0) throw Error('FRET seed failed: '+seeded.stderr);
 for(const r of input.requirements){
  const p=cp.spawnSync(process.execPath,['/opt/probe/dist/cli.cjs','formalize','-l','ft-inf',r.text],{env,encoding:'utf8',timeout:60000});
  fs.writeFileSync(path.join(out,r.id+'.formalize.log'),p.stdout+p.stderr);
  if(p.status!==0) throw Error(`FRET formalize failed for ${r.id}`);
 }
 const timeout=Number(input.timeout||60);
 if(!Number.isInteger(timeout)||timeout<1||timeout>600) throw Error('timeout must be integer 1..600 seconds');
 const args=['/opt/probe/dist/cli.cjs','--debug','realizability','--solver','jkind','--diagnose','--timeout',String(timeout),'--json',path.join(out,'realizability.json'),input.project,input.component];
 const checked=cp.spawnSync(process.execPath,args,{env,encoding:'utf8',timeout:(timeout*20+60)*1000,maxBuffer:10*1024*1024});
 fs.writeFileSync(path.join(out,'realizability.log'),checked.stdout+checked.stderr);
 const dir=path.join(home,'Documents/fret-analysis');
 if(fs.existsSync(dir)) fs.cpSync(dir,path.join(out,'solver'),{recursive:true});
 if(checked.status!==0) throw Error('FRET CLI failed: '+checked.stderr);
 if(!fs.existsSync(path.join(out,'realizability.json'))) throw Error('FRET did not produce a report');
 const report=JSON.parse(fs.readFileSync(path.join(out,'realizability.json')));
 const comp=report.systemComponents.find(c=>c.name===input.component);
 const analysis=comp.compositional.result==='UNCHECKED'?comp.monolithic:comp.compositional;
 const summary={sourceSHA:SHA,project:input.project,component:input.component,result:analysis.result,solver:'jkind',diagnosis:analysis.diagnosisReport||analysis.connectedComponents?.map(c=>c.diagnosisReport)};
 fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(summary,null,2));
 console.log(JSON.stringify(summary,null,2));
 if(!['REALIZABLE','UNREALIZABLE'].includes(summary.result)) process.exitCode=2;
}
main().catch(e=>{console.error(e.stack);process.exitCode=1;});
