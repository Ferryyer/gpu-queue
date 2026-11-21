// The desktop detail remains in the workbench. On narrow screens it becomes
// a named modal; isolate every sibling along its ancestor chain, not just the list.
export function detailModal(panel, {onClose, returnFocus}) {
 let opened=false, isolated=[];
 const controls=(root=panel)=>[...root.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]')].filter(el=>el.tabIndex>=0&&!el.closest('[inert]')&&el.getClientRects().length);
 const focusFirst=()=> (controls()[0]||panel).focus({preventScroll:true});
 function keydown(event){
  if(!opened)return;
  const nested=document.querySelector('dialog[open]');
  if(event.key==='Escape'){if(!nested){event.preventDefault();onClose();}return;}
  if(event.key!=='Tab'||event.ctrlKey||event.altKey||event.metaKey)return;
  const items=controls(nested||panel),index=items.indexOf(document.activeElement);
  if(!items.length){event.preventDefault();panel.focus();}
  else if(index<0||!event.shiftKey&&index===items.length-1||event.shiftKey&&index===0){
   event.preventDefault();items[event.shiftKey?items.length-1:0].focus();
  }
 }
 document.addEventListener('keydown',keydown,true);
 document.addEventListener('focusin',event=>{
  if(opened&&!panel.contains(event.target)&&!event.target.closest('dialog[open]'))focusFirst();
 });
 return {
  get opened(){return opened;},
  sync(open){
   if(open===opened)return;
   opened=open;
   if(open){
    panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.tabIndex=-1;
    for(let node=panel;node.parentElement&&node!==document.body;node=node.parentElement){
     for(const sibling of node.parentElement.children){
      if(sibling===node||sibling.matches('dialog,#toast,script,style'))continue;
      isolated.push([sibling,sibling.inert]);sibling.inert=true;
     }
    }
    focusFirst();
   }else{
    panel.removeAttribute('role');panel.removeAttribute('aria-modal');panel.removeAttribute('tabindex');
    for(const [node,inert] of isolated)node.inert=inert;
    isolated=[];
    returnFocus();
   }
  },
  ensureFocus(){if(opened&&!panel.contains(document.activeElement)&&!document.querySelector('dialog[open]'))focusFirst();}
 };
}
