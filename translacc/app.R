library(shiny)
library(ggplot2)
library(lubridate)


stop_times = c('10:00am','10:00pm','10:10am','10:15am','10:20am','10:25pm','10:30am','10:30pm','10:45am','10:50pm','11:00am','11:00pm','11:10am','11:15am','11:15pm','11:30am','11:30pm','11:35am','11:40pm','11:45am','12:00am','12:00pm','12:05am','12:15pm','12:25pm','12:30am','12:30pm','12:45pm','12:50pm','1:00pm','1:15pm','1:30pm','1:40pm','1:45pm','2:00pm','2:05pm','2:15pm','2:30pm','2:45pm','2:55pm','3:00pm','3:06pm','3:12pm','3:15pm','3:18pm','3:20pm','3:24pm','3:30pm','3:36pm','3:42pm','3:45pm','3:48pm','3:54pm','4:00pm','4:06pm','4:10pm','4:12pm','4:18pm','4:24pm','4:30pm','4:35pm','4:36pm','4:42pm','4:48pm','4:54pm','5:00pm','5:06pm','5:12pm','5:18pm','5:24pm','5:25pm','5:30pm','5:36pm','5:42pm','5:48pm','5:50pm','5:54pm','6:00am','6:00pm','6:10pm','6:15am','6:15pm','6:20pm','6:30am','6:30pm','6:40pm','6:45am','6:45pm','6:50pm','7:00am','7:00pm','7:05pm','7:15am','7:15pm','7:25am','7:30am','7:30pm','7:36am','7:42am','7:45pm','7:48am','7:50am','7:54am','7:55pm','8:00am','8:00pm','8:06am','8:12am','8:15am','8:15pm','8:18am','8:20pm','8:24am','8:30am','8:30pm','8:36am','8:40am','8:42am','8:45pm','8:48am','8:54am','9:00am','9:00pm','9:05am','9:06am','9:10am','9:10pm','9:12am','9:18am','9:20am','9:24am','9:30am','9:30pm','9:35pm','9:40am','9:50am','9:55am')

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
                                         value = c(as.POSIXct("2017-01-01 06:00:00"),
                                                   as.POSIXct("2017-01-01 23:59:00")),   
                                         timeFormat="%T",   
                                         step = 30),
                             numericInput("min_miss_time","Missed Bus Time",value=15,min = 1,max = 60,step = 1),
                             selectInput("day",
                                         "Day",
                                         c("Weekday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"),
                                         selected="Monday"),
                             selectInput("stop_time",
                                         "Stop Time",
                                         stop_times,
                                         selected=stop_times[1])
                           ),
                           mainPanel(
                             textOutput("total_missed"),
                             textOutput("total_late"),
                             textOutput("range_missed"),
                             textOutput("range_late"),
                             plotOutput("plot_main"),
                             plotOutput("plot_missed_day"),
                             plotOutput("plot_late_day"),
                             plotOutput("plot_late_time"),
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
cdf$day = lubridate::wday(cdf$scheduled,label=TRUE,abbr=FALSE)
cdf$scheduled_time = strftime(cdf$scheduled, format="%H:%M:%S",tz="EST")
cdf$date <- as.Date(cdf$scheduled)


# Define server logic required to draw a histogram
server <- function(input, output) {
  #autoInvalidate <- reactiveTimer(15000)
  #observe({
  #  autoInvalidate()
  #  ldf <- read.table(file = '/home/sparrow/soft/transloc/log.tsv.edited.tsv', sep = '\t', header = TRUE,colClasses=c("character","character","POSIXct","numeric"))
  #  ldf = ldf[seq(1, nrow(ldf), 25), ]
  #  
  #  odf <- read.table(file = '/home/sparrow/soft/transloc/log.tsv.observed.tsv', sep = '\t', header = TRUE,colClasses=c("POSIXct","numeric","character","numeric"))
  #  
  #  cdf=read.table(file = '/home/sparrow/soft/transloc/log.tsv.closest.tsv', sep = "\t", header = TRUE,colClasses=c("POSIXct","POSIXct","POSIXct","character"))
  #  cdf = cdf[order(cdf$scheduled),]
  #  cdf$diffs = abs(difftime(cdf$scheduled,cdf$observed_all,units="hours"))
  #  cdf$date <- as.Date(cdf$scheduled)
  #})
  
  
  vals <- reactiveValues()

  observe({
    testdatetime <- paste(input$date,strftime(input$time, format="%H:%M:%S"))
    testdatetime <- as.POSIXct(testdatetime, format="%Y-%m-%d %H:%M:%S",tz= "EST")
    vals$start_datetime <- testdatetime[1]
    vals$end_datetime <- testdatetime[2]
    vals$stop <- input$stop
    vals$min_miss_time = input$min_miss_time
    vals$day = input$day
    vals$stop_time = input$stop_time
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
  
  output$plot_late_time <- renderPlot({
    lt = strptime(vals$stop_time, '%I:%M%p')
    s=NULL
    if(vals$day=="Weekday"){
      s = cdf[(cdf$stop == vals$stop) & (cdf$day %in% c("Monday","Tuesday","Wednesday","Thursday","Friday")) & (cdf$scheduled_time==strftime(lt,format="%H:%M:%S")),]
    }
    else{
      s = cdf[(cdf$stop == vals$stop) & (cdf$day==vals$day) & (cdf$scheduled_time==strftime(lt,format="%H:%M:%S")),]
    }
    
    p<-ggplot(s, aes(x=diffs)) + geom_histogram()
    p
  })
}

# Run the application 
shinyApp(ui = ui, server = server)
