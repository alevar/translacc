#
# This is a Shiny web application. You can run the application by clicking
# the 'Run App' button above.
#
# Find out more about building applications with Shiny here:
#
#    http://shiny.rstudio.com/
#

library(shiny)
library(ggplot2)

saveData <- function(input) {
  # put variables in a data frame
  data <- data.frame(matrix(nrow=1,ncol=0))
  for (x in fields) {
    var <- input[[x]]
    if (length(var) > 1 ) {
      data[[x]] <- list(var)
    } else {
      # all other data types
      data[[x]] <- var
    }
  }
  data$submit_time <- date()
  
  # Create a unique file name
  fileName <- sprintf(
    "%s_%s.rds", 
    as.integer(Sys.time()), 
    digest::digest(data)
  )
  
  # Write the file to the local system
  saveRDS(
    object = data,
    file = file.path(outputDir, fileName)
  )
}

# Define UI for application that draws a histogram
ui <- fluidPage(

    # Application title
    titlePanel("Transloc Bus \"Accuracy\""),
    
    tabsetPanel(type = "tabs",
                tabPanel("Data", br(),
                         sidebarLayout(
                           sidebarPanel(
                             selectInput(
                               "stop",
                               "Stop",
                               c("Broadway","Interfaith"),
                               selected = "Broadway"
                             ),
                             dateInput(inputId='date',label = 'Select Date', value = Sys.Date()-2),
                             sliderInput("time", "Select Time Range",   
                                            min = as.POSIXct("2017-01-01 00:00:00"),   
                                         max = as.POSIXct("2017-01-01 24:00:00"),   
                                         value = c(as.POSIXct("2017-01-01 12:00:00"),
                                                   as.POSIXct("2017-01-01 18:00:00")),   
                                         timeFormat="%T",   
                                         step = 30),
                             numericInput("min_miss_time","Missed Bus Time",value=15,min = 1,max = 60,step = 1),
                           ),
                           mainPanel(
                             textOutput("total_missed"),
                             textOutput("total_late"),
                             textOutput("range_missed"),
                             textOutput("range_late"),
                             plotOutput("plot_main"),
                             plotOutput("plot_missed_day"),
                             plotOutput("plot_late_day"),
                             tableOutput("table"),
                           ),
                         )
                  ),
                tabPanel("Feedback", br(),
                         fluidRow(
                           column(12, wellPanel(p("Feedback Form")))),
                ),
    ),
)

ldf <- read.table(file = '/home/sparrow/soft/transloc/log.tsv.edited.tsv', sep = '\t', header = TRUE,colClasses=c("character","character","POSIXct","numeric"))
ldf = ldf[seq(1, nrow(ldf), 25), ]

odf <- read.table(file = '/home/sparrow/soft/transloc/log.tsv.observed.tsv', sep = '\t', header = TRUE,colClasses=c("POSIXct","numeric","character","numeric"))

cdf=read.table(file = '/home/sparrow/soft/transloc/log.tsv.closest.tsv', sep = "\t", header = TRUE,colClasses=c("POSIXct","POSIXct","POSIXct","character"))
cdf = cdf[order(cdf$scheduled),]
cdf$diffs = abs(difftime(cdf$scheduled,cdf$observed_all,units="hours"))
cdf$date <- as.Date(cdf$scheduled)


# Define server logic required to draw a histogram
server <- function(input, output) {
  vals <- reactiveValues()

  observe({
    testdatetime <- paste(input$date,strftime(input$time, format="%H:%M:%S"))
    testdatetime <- as.POSIXct(testdatetime, format="%Y-%m-%d %H:%M:%S",tz= "EST")
    vals$start_datetime <- testdatetime[1]
    vals$end_datetime <- testdatetime[2]
    vals$stop <- input$stop
    vals$min_miss_time = input$min_miss_time
  })
  
  observeEvent(input$submit, {
    saveData(input)
    resetForm(session)
  })
  
  output$feedback <- renderPrint({
    feedback(d())
  })
  
  output$total_missed <- renderText({
    missed = cdf[cdf["diffs"]>=vals$min_miss_time/60,]
    paste(c("Total number of missed busses since ",strftime(min(ldf$time)),": ", nrow(missed)), collapse = " ")
  })
  
  output$total_late <- renderText({
    paste(c("Total amount of time wasted by busses being late since",strftime(min(ldf$time)),": ", round(sum(cdf$diffs),0)," hours"), collapse = " ")
  })
  
  output$table <- renderTable({
    t = cdf[cdf$stop == vals$stop & cdf$scheduled>=vals$start_datetime & cdf$scheduled<=vals$end_datetime,]
    t$scheduled <- strftime(t$scheduled, format="%Y-%m-%d %H:%M:%S")
    t$observed <- strftime(t$observed, format="%Y-%m-%d %H:%M:%S")
    t
  })
  
  output$plot_main <- renderPlot({
    scdf = cdf[cdf$stop==vals$stop & cdf$scheduled>=vals$start_datetime & cdf$scheduled<=vals$end_datetime,]
    sldf = ldf[ldf$sid==vals$stop & ldf$time>=vals$start_datetime & ldf$time<=vals$end_datetime,]
    sodf = odf[odf$stop==vals$stop & odf$time>=vals$start_datetime & odf$time<=vals$end_datetime,]
    
    g <- ggplot(NULL) +
      geom_line(data=sldf,aes(x=time, y=dist, group=vid, color=vid)) +
      geom_point(data=sodf, aes(x=time,y=dist),size=3,colour="red") + 
      geom_vline(data=scdf, aes(xintercept=scheduled))+
      ggtitle("Bus Routes At Time Interval:") +
      ylab("Distance")
    g
  })
  
  output$plot_missed_day <- renderPlot({
    missed = cdf[cdf["diffs"]>=vals$min_miss_time/60,]
    
    tcdf = missed[missed$stop==vals$stop,]
    mcdf = aggregate(tcdf$diffs, by=list(tcdf$date),length)
    names(mcdf) = c("date","count")
    
    p<-ggplot(data=mcdf, aes(x=date, y=count)) +
      geom_bar(stat="identity")
    p
  })
  
  output$plot_late_day <- renderPlot({
    tcdf = cdf[cdf$stop==vals$stop,]
    rcdf = aggregate(tcdf$diffs, by=list(tcdf$date), sum)
    names(rcdf) = c("date","hrs")
    
    p<-ggplot(data=rcdf, aes(x=date, y=hrs)) +
      geom_bar(stat="identity")
    p
  })
}

# Run the application 
shinyApp(ui = ui, server = server)
